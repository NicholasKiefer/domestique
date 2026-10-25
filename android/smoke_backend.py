#!/usr/bin/env python3
# Copyright (c) 2026 Domestique contributors
# SPDX-License-Identifier: Apache-2.0
"""Exercise the packaged backend with Android's dependency versions on a host.

Run after assembleDebug using a Python 3.10 venv with app/requirements.txt.
This tests the bundle, not the checkout, and never opens the user's profile.
"""
import json
from pathlib import Path
import sys
import tempfile
import urllib.request

sys.path.insert(0, str(Path(__file__).parent / "app/src/main/python"))
import android_backend


def main():
    archive = Path(__file__).parent / "app/build/generated/backend/backend.zip"
    if not archive.exists():
        raise SystemExit("Build the APK first: backend.zip is missing")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with tempfile.TemporaryDirectory(prefix="domestique-android-smoke-") as files:
        url = android_backend.start(archive, files)

        def request(path, payload=None):
            req = urllib.request.Request(
                url + path, data=json.dumps(payload).encode() if payload is not None else None,
                headers={"Content-Type": "application/json"},
            )
            with opener.open(req, timeout=180) as response:
                return response.read()

        try:
            assert json.loads(request("/api/version"))["app"] == "domestique"
            assert b"Setup" in request("/setup")
            assert json.loads(request("/api/setup/save", {
                "ftp": 220, "weight": 75, "hours_per_week": 6,
                "available_days": [1, 2, 3, 4, 5, 6], "rest_days": [0],
            }))["ok"]
            assert b"Planner &amp; Library" in request("/") or b"Planner & Library" in request("/")
            workouts = json.loads(request("/api/workouts?limit=5"))
            assert workouts, "Packaged workout library is empty"
            plan = json.loads(request("/api/plan/generate", {
                "goal": "general", "weeks": 4, "hours_per_week": 6,
                "rest_days": [0], "ftp": 220,
            }))
            assert "error" not in plan, plan
            assert list(Path(files).glob("athlete-data/profiles/*/athlete.json"))
            print("PASS: packaged backend startup, setup, dashboard, workout library, plan generation")
        finally:
            android_backend.stop()


if __name__ == "__main__":
    main()
