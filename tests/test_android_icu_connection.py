# Copyright (c) 2026 Domestique contributors
# SPDX-License-Identifier: Apache-2.0
"""Exercise credential discovery, persistence, sync and Android reads over HTTP.

Only the remote destination is redirected to a local API fixture. Application
auth/header construction, both HTTP clients, persistence and sync are real.
"""
import base64
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
from urllib.parse import urlsplit
from urllib.request import Request

from fastapi.testclient import TestClient
import httpx
import pytest

import app
import clock
import config
import db
from profile_manager import ProfileManager
import training


@contextmanager
def local_icu(monkeypatch):
    expected = "Basic " + base64.b64encode(b"API_KEY:integration-test-key").decode()
    state = {"wellness_status": 200, "calls": []}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            path = urlsplit(self.path).path
            authorized = self.headers.get("Authorization") == expected
            state["calls"].append((path, authorized, self.headers.get("User-Agent", "")))
            status = 200 if authorized else 401
            today = clock.today().isoformat()
            if path.endswith("/wellness"):
                if authorized:
                    status = state["wellness_status"]
                payload = [{"id": today, "ctl": 43, "atl": 36, "hrv": 64,
                            "restingHR": 49, "sleepSecs": 28800,
                            "sportInfo": [{"eftp": 235}]}]
            elif path.endswith("/activities"):
                payload = [{"id": "i-fixture-ride", "name": "Fixture ride", "type": "Ride",
                            "start_date_local": today + "T08:00:00", "moving_time": 3600,
                            "icu_training_load": 55, "average_watts": 180}]
            else:
                payload = {"id": "i-fixture", "name": "Fixture rider", "weight": 72}
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(payload if status == 200 else {"error": "denied"}).encode())

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    origin = f"http://127.0.0.1:{server.server_port}"
    real_httpx_get = httpx.get

    def redirect_urlopen(request, **kwargs):
        parsed = urlsplit(request.full_url)
        assert parsed.scheme == "https" and parsed.netloc == "intervals.icu"
        redirected = Request(origin + parsed.path + ("?" + parsed.query if parsed.query else ""),
                             headers=dict(request.header_items()))
        return training._REAL_URLOPEN(redirected, timeout=5)

    def redirect_httpx(url, **kwargs):
        parsed = urlsplit(url)
        assert parsed.scheme == "https" and parsed.netloc == "intervals.icu"
        return real_httpx_get(origin + parsed.path + ("?" + parsed.query if parsed.query else ""), **kwargs)

    monkeypatch.setattr(training.urllib.request, "urlopen", redirect_urlopen)
    monkeypatch.setattr(httpx, "get", redirect_httpx)
    try:
        yield state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_android_connection_fetches_and_persists_real_sync_results(monkeypatch):
    monkeypatch.setenv("DOMESTIQUE_PLATFORM", "android")
    monkeypatch.setattr(db, "start_background_sync", lambda: None)
    monkeypatch.setattr(app, "_kick_lazy_icu_sync", lambda **kw: False)
    with local_icu(monkeypatch) as remote, TestClient(app.app) as client:
        pm = ProfileManager.get()
        pm.switch(pm.create_profile("Android ICU integration"))
        checked = client.post("/api/setup/test-icu", json={"api_key": "integration-test-key"}).json()
        assert checked["ok"] and checked["athlete_id"] == "i-fixture"
        saved = client.post("/api/setup/save", json={
            "icu_api_key": "integration-test-key", "icu_athlete_id": checked["athlete_id"]}).json()
        assert saved["ok"] and saved["creds_test"] == "passed"
        # Reload the saved credentials, rather than relying on the setup call's memory.
        pm._env = pm._load_env_file(pm.active_dir / ".env")
        assert config.ICU_ATHLETE_ID == "i-fixture"
        synced = client.post("/api/sync").json()
        assert synced["status"] == "ok"
        assert synced["wellness"] == 1 and synced["activities"] == 1
        status = client.get("/api/sync/status").json()
        assert status["last_sync"]["status"] == "ok"
        assert status["wellness_records"] == 1 and status["activity_records"] == 1
        metrics = client.get("/api/readiness").json()
        assert metrics["training"]["ctl"] == 43
        assert metrics["training"]["atl"] == 36
        assert metrics["sleep"]["sleep_h"] == 8
        assert client.get("/api/activities").json()[0]["name"] == "Fixture ride"
        calls_before_reads = len(remote["calls"])
        client.get("/api/readiness")
        client.get("/api/wellness")
        assert len(remote["calls"]) == calls_before_reads
        assert all(authorized for _, authorized, _ in remote["calls"])
        assert all(not ua.startswith("Python-urllib/") for _, _, ua in remote["calls"])
        # A working athlete lookup must not mask a denied wellness feed.
        remote["wellness_status"] = 401
        with pytest.raises(training.ICUAuthError):
            db.run_sync(days=90)
        assert db.get_sync_status()["last_sync"]["status"] == "error"
        assert not client.post("/api/setup/test-icu", json={"api_key": "wrong-key"}).json()["ok"]
