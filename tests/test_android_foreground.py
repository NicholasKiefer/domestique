# Copyright (c) 2026 Domestique contributors
# SPDX-License-Identifier: Apache-2.0
"""Mobile foreground reads stay local while explicit sync keeps the transport."""
import json
import threading

from fastapi.testclient import TestClient
import app
import clock
import db
import icu_snapshot
import training


def test_android_views_read_synced_metrics_without_live_icu(monkeypatch):
    monkeypatch.setenv("DOMESTIQUE_PLATFORM", "android")
    monkeypatch.setattr(db, "start_background_sync", lambda: None)
    monkeypatch.setattr(app, "_kick_lazy_icu_sync", lambda **kw: False)
    monkeypatch.setattr(training, "_require_credentials", lambda: None)
    network_calls = []
    def blocked(*args, **kwargs):
        network_calls.append(args)
        raise AssertionError("Foreground read attempted a live ICU request")
    monkeypatch.setattr(training, "_get", blocked)
    with TestClient(app.app) as client:
        connection = db.get_db()
        day = clock.today().isoformat()
        connection.execute(
            "INSERT OR REPLACE INTO wellness(date,ctl,atl,hrv,rhr,sleep_secs,raw_json) VALUES(?,?,?,?,?,?,?)",
            (day, 42, 35, 60, 48, 28800, json.dumps({"id": day, "ctl": 42, "atl": 35})))
        connection.commit()
        app.clear_cache()
        response = client.get("/api/readiness")
        assert response.status_code == 200, response.text
        assert response.json()["training"]["ctl"] == 42
        assert response.json()["training"]["atl"] == 35
        assert response.json()["sleep"]["sleep_h"] == 8
        assert client.get("/api/plan").status_code == 200
        assert network_calls == []
        sync_context = []
        def sync(**kwargs):
            sync_context.append(icu_snapshot.prefer_local.get())
            sql = db.get_db()
            sql.execute("UPDATE wellness SET ctl=55 WHERE date=?", (day,))
            sql.commit()
            return {"status": "ok"}
        monkeypatch.setattr(db, "run_sync", sync)
        assert client.post("/api/sync").status_code == 200
        assert sync_context == [False]
        assert client.get("/api/readiness").json()["training"]["ctl"] == 55
        monkeypatch.setattr(app, "_sync_icu_rides_and_wellness", lambda **kw: {"status": "ok", "added": 0})
        monkeypatch.setattr(app, "_detect_plan_load_alert", lambda: False)
        monkeypatch.setattr(app, "_maybe_auto_reforecast", lambda *a: None)
        assert client.post("/api/rides/sync?force=1").json()["status"] == "ok"
        assert sync_context == [False, False]
    assert not icu_snapshot.prefer_local.get()


def test_snapshot_keeps_raw_fields_and_persisted_manual_values(monkeypatch):
    monkeypatch.setattr(db, "query_wellness", lambda days: [{
        "date": "2026-10-25", "ctl": 40, "hrv": 70,
        "raw_json": json.dumps({"id": "2026-10-25", "hrv": None,
                                 "sportInfo": [{"eftp": 230}], "weight": 72})}])
    record = icu_snapshot.wellness(7)[0]
    assert record["hrv"] == 70
    assert record["sportInfo"][0]["eftp"] == 230
    assert record["weight"] == 72


def test_background_worker_does_not_inherit_foreground_snapshot():
    token = icu_snapshot.prefer_local.set(True)
    seen = []
    try:
        worker = threading.Thread(target=lambda: seen.append(icu_snapshot.prefer_local.get()))
        worker.start()
        worker.join(timeout=2)
        assert seen == [False]
    finally:
        icu_snapshot.prefer_local.reset(token)
