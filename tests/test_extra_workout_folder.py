"""3.13.1 — the built-in library is always the library; a rider's own folder
ADDS workouts to it (it used to replace it, and then lacked every workout
shipped later: "no cp_test workout in library", tester report on 3.13.0).

A folder that is itself a Domestique built-in library (the setup wizard
saved the install's own path, so many profiles point at an old install) is
never an extra folder.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import training_planner as tp
from test_icu_push import stub  # noqa: F401  (fixture: sandboxed HOME + TestClient)

BUNDLED = tp._BUNDLED_WORKOUT_DIR
CP = "ftp_test_cp_12-7-3min_100pct_110min.zwo"
MINE = """<workout_file><name>My Hill Repeats</name><workout>
<Warmup Duration="600" PowerLow="0.5" PowerHigh="0.7"/>
<IntervalsT Repeat="5" OnDuration="180" OffDuration="180" OnPower="1.05" OffPower="0.5"/>
<Cooldown Duration="300" PowerLow="0.6" PowerHigh="0.4"/></workout></workout_file>"""


def _own_folder(root: Path) -> Path:
    own = root / "My Workouts"
    own.mkdir()
    (own / "my_hill_repeats.zwo").write_text(MINE, encoding="utf-8")
    # a file the built-in library also has: the built-in one wins
    (own / "endurance_steady_68pct_120min.zwo").write_text(MINE, encoding="utf-8")
    return own


def test_the_library_is_built_in_plus_the_extra_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(tp, "WORKOUT_DIR", BUNDLED)
    monkeypatch.setattr(tp, "EXTRA_WORKOUT_DIR", None)
    base = tp.load_workout_library()
    assert any(w["File"] == CP for w in base)
    monkeypatch.setattr(tp, "EXTRA_WORKOUT_DIR", _own_folder(tmp_path))
    lib = tp.load_workout_library()
    files = [w["File"] for w in lib]
    assert len(lib) == len(base) + 1 and "my_hill_repeats.zwo" in files
    assert files.count("endurance_steady_68pct_120min.zwo") == 1
    steady = next(w for w in lib if w["File"] == "endurance_steady_68pct_120min.zwo")
    assert steady["Name"] != "My Hill Repeats"            # the built-in row
    assert CP in files                                     # always there


def test_a_copy_of_the_built_in_library_is_never_an_extra_folder(tmp_path):
    old = tmp_path / "Domestique-3.12.2" / "_internal" / "workouts"
    old.mkdir(parents=True)
    (old / "endurance_steady_68pct_120min.zwo").write_text(MINE, encoding="utf-8")
    (old / ".overhaul_manifest.json").write_text("{}", encoding="utf-8")
    assert tp.extra_workout_dir_for(old) is None
    assert tp.extra_workout_dir_for(BUNDLED) is None
    empty = tmp_path / "empty"
    empty.mkdir()
    assert tp.extra_workout_dir_for(empty) is None
    assert tp.extra_workout_dir_for(_own_folder(tmp_path)) is not None


def test_a_saved_folder_resolves_as_extra_and_the_built_in_stays(stub):
    import app as app_module
    own = _own_folder(stub.home)
    (stub.pm.active_dir / "user_paths.json").write_text(json.dumps({"workout_dir": str(own)}))
    stub.pm.apply_training_dirs()
    app_module._apply_profile_paths()
    assert tp.WORKOUT_DIR.resolve() == BUNDLED.resolve()
    assert tp.EXTRA_WORKOUT_DIR == own and app_module.EXTRA_WORKOUT_DIR == own
    assert app_module._workout_file("my_hill_repeats.zwo") == (own / "my_hill_repeats.zwo").resolve()
    assert app_module._workout_file(CP) == (BUNDLED / CP).resolve()
    steady = app_module._workout_file("endurance_steady_68pct_120min.zwo")
    assert steady.parent == BUNDLED.resolve()


def test_an_old_install_path_saved_by_setup_is_ignored(stub):
    import app as app_module
    old = stub.home / "Downloads" / "Domestique-3.12.2" / "_internal" / "workouts"
    old.mkdir(parents=True)
    (old / "z2_old_name_60min.zwo").write_text(MINE, encoding="utf-8")
    (old / ".overhaul_manifest.json").write_text("{}", encoding="utf-8")
    (stub.pm.active_dir / "user_paths.json").write_text(json.dumps({"workout_dir": str(old)}))
    stub.pm.apply_training_dirs()
    app_module._apply_profile_paths()
    assert tp.EXTRA_WORKOUT_DIR is None and app_module.EXTRA_WORKOUT_DIR is None
    assert tp.WORKOUT_DIR.resolve() == BUNDLED.resolve()


def test_settings_set_show_and_clear_the_extra_folder(stub):
    c = stub.client
    st = c.get("/api/settings/workout-folders").json()
    assert st["extra"] is None and st["builtin"]["count"] >= 4000
    own = _own_folder(stub.home)
    r = c.post("/api/settings/workout-folders", json={"extra_dir": str(own)})
    assert r.status_code == 200, r.text
    assert r.json()["extra"] == {"path": str(own), "files": 2, "added": 1}
    assert json.loads((stub.pm.active_dir / "user_paths.json").read_text())["workout_dir"] == str(own)
    assert tp.EXTRA_WORKOUT_DIR == own
    assert any(w["File"] == "my_hill_repeats.zwo" for w in tp.load_workout_library())
    r = c.post("/api/settings/workout-folders", json={"extra_dir": ""})
    assert r.status_code == 200 and r.json()["extra"] is None
    assert "workout_dir" not in json.loads((stub.pm.active_dir / "user_paths.json").read_text())
    assert tp.EXTRA_WORKOUT_DIR is None


@pytest.mark.parametrize("why", ["no .zwo", "outside home", "the built-in library"])
def test_settings_refuse_a_folder_that_cannot_be_an_extra_library(stub, why):
    p = {"no .zwo": stub.home / "nothing_here", "outside home": Path("/etc"),
         "the built-in library": BUNDLED}[why]
    if why == "no .zwo":
        p.mkdir()
    r = stub.client.post("/api/settings/workout-folders", json={"extra_dir": str(p)})
    assert r.status_code == 400 and r.json()["error"], why
    assert tp.EXTRA_WORKOUT_DIR is None
