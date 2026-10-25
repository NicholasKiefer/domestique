# Copyright (c) 2026 Domestique contributors
# SPDX-License-Identifier: Apache-2.0
"""Android-only bootstrap; the existing backend remains shared with desktop."""
import hashlib
import os
from pathlib import Path
import shutil
import socket
import sys
import threading
import time
import urllib.request
import zipfile

_server = None
_thread = None
_url = None
_lock = threading.Lock()


def unpack_backend(archive, runtime_dir):
    """Version the read-only application bundle separately from athlete data."""
    archive = Path(archive)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()[:16]
    root = Path(runtime_dir)
    target = root / digest
    if not (target / ".complete").exists():
        root.mkdir(parents=True, exist_ok=True)
        stage = root / (digest + ".tmp")
        shutil.rmtree(stage, ignore_errors=True)
        stage.mkdir()
        try:
            with zipfile.ZipFile(archive) as bundle:
                for member in bundle.infolist():
                    dest = (stage / member.filename).resolve()
                    if not dest.is_relative_to(stage.resolve()):
                        raise ValueError("Invalid backend archive path")
                bundle.extractall(stage)
            (stage / ".complete").touch()
            shutil.rmtree(target, ignore_errors=True)
            stage.rename(target)
        except BaseException:
            shutil.rmtree(stage, ignore_errors=True)
            raise
    return target


def start(archive, files_dir):
    """Start one in-process loopback server, returning only when it is ready.

    Called on a Java worker, never the UI thread. Android can terminate the
    process in the background; a subsequent launch boots from persisted data.
    """
    global _server, _thread, _url
    with _lock:
        if _thread is not None and _thread.is_alive() and _server.started:
            return _url
        files_dir = Path(files_dir)
        bundle = unpack_backend(archive, files_dir / "runtime")
        os.environ["DOMESTIQUE_HOME"] = str(files_dir / "athlete-data")
        os.environ["DOMESTIQUE_PLATFORM"] = "android"
        sys.path.insert(0, str(bundle / "src"))

        # Reserve an available port before config.py resolves its OAuth redirect.
        port_file = files_dir / "server-port"
        try:
            preferred_port = int(port_file.read_text())
            if not 1024 <= preferred_port <= 65535:
                preferred_port = 0
        except (OSError, ValueError):
            preferred_port = 0
        sock = socket.socket()
        try:
            sock.bind(("127.0.0.1", preferred_port))
        except OSError:
            sock.bind(("127.0.0.1", 0))
        sock.listen(128)
        port = sock.getsockname()[1]
        os.environ["DOMESTIQUE_PORT"] = str(port)
        _url = f"http://127.0.0.1:{port}"
        try:
            import uvicorn
            from app import app

            _server = uvicorn.Server(uvicorn.Config(
                app, host="127.0.0.1", port=port, loop="asyncio", http="h11",
                lifespan="on", access_log=False, log_config=None,
            ))
            _thread = threading.Thread(
                target=_server.run, kwargs={"sockets": [sock]},
                name="domestique-server", daemon=True,
            )
            _thread.start()
            # No inherited proxy should handle the app's own loopback traffic.
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            deadline = time.monotonic() + 90
            while time.monotonic() < deadline:
                if not _thread.is_alive():
                    raise RuntimeError("The local backend stopped during startup. See logcat/Python.")
                if _server.started:
                    try:
                        with opener.open(_url + "/api/version", timeout=2) as response:
                            if response.status == 200:
                                port_file.write_text(str(port))
                                return _url
                    except OSError:
                        pass
                time.sleep(0.1)
            raise TimeoutError("The local backend did not become ready within 90 seconds.")
        except BaseException:
            if _server is not None:
                _server.should_exit = True
            if _thread is not None:
                _thread.join(timeout=5)
            sock.close()
            raise


def stop():
    """For instrumentation/host smoke tests; normal exit follows process lifetime."""
    if _server is not None:
        _server.should_exit = True
    if _thread is not None:
        _thread.join(timeout=10)
