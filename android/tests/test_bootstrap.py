# Copyright (c) 2026 Domestique contributors
# SPDX-License-Identifier: Apache-2.0
"""Host checks for installation/update safety (no Android SDK required)."""
import importlib.util
from pathlib import Path
import zipfile

import pytest

MODULE = Path(__file__).parents[1] / "app/src/main/python/android_backend.py"
spec = importlib.util.spec_from_file_location("android_backend", MODULE)
backend = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backend)


def make_bundle(path, content="version one"):
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("src/app.py", content)
        archive.writestr("src/workouts/example.zwo", "<workout/>")


def test_bundle_relaunch_and_upgrade_preserve_athlete_data(tmp_path):
    bundle = tmp_path / "backend.zip"
    runtime = tmp_path / "runtime"
    athlete = tmp_path / "athlete-data/profile.json"
    athlete.parent.mkdir()
    athlete.write_text('"my profile"')
    make_bundle(bundle)
    first = backend.unpack_backend(bundle, runtime)
    (first / "src/workouts/generated.zwo").write_text("generated")
    assert backend.unpack_backend(bundle, runtime) == first
    assert (first / "src/workouts/generated.zwo").exists()
    make_bundle(bundle, "version two")
    second = backend.unpack_backend(bundle, runtime)
    assert first != second
    assert (second / "src/app.py").read_text() == "version two"
    assert athlete.read_text() == '"my profile"'


def test_archive_cannot_escape_runtime(tmp_path):
    bundle = tmp_path / "bad.zip"
    with zipfile.ZipFile(bundle, "w") as archive:
        archive.writestr("../../escaped", "bad")
    with pytest.raises(ValueError, match="archive path"):
        backend.unpack_backend(bundle, tmp_path / "runtime")
    assert not (tmp_path / "escaped").exists()
    assert list((tmp_path / "runtime").iterdir()) == []


def test_incomplete_install_is_replaced(tmp_path):
    bundle = tmp_path / "backend.zip"
    make_bundle(bundle)
    installed = backend.unpack_backend(bundle, tmp_path / "runtime")
    (installed / ".complete").unlink()
    (installed / "src/app.py").write_text("incomplete")
    backend.unpack_backend(bundle, tmp_path / "runtime")
    assert (installed / "src/app.py").read_text() == "version one"
