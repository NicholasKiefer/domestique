# Copyright (c) 2026 Domestique contributors
# SPDX-License-Identifier: Apache-2.0
"""Request-local ICU snapshots for Android's foreground views.

Sync workers keep the real transport. ContextVars propagate into FastAPI's
worker threads, but not into the independent background sync threads.
"""
from contextvars import ContextVar
import json

prefer_local = ContextVar("icu_prefer_local", default=False)


def _raw(row):
    try:
        value = json.loads(row.get("raw_json") or "{}")
    except (ValueError, TypeError):
        value = {}
    return value if isinstance(value, dict) else {}


def wellness(days):
    import db
    result = []
    for row in db.query_wellness(days):
        record = _raw(row)
        record["id"] = row["date"]
        for column, field in (("ctl", "ctl"), ("atl", "atl"), ("hrv", "hrv"),
                              ("rhr", "restingHR"), ("sleep_secs", "sleepSecs"),
                              ("sleep_score", "sleepScore")):
            if row.get(column) is not None:
                record[field] = row[column]
        if row.get("eftp") is not None and not record.get("sportInfo"):
            record["sportInfo"] = [{"eftp": row["eftp"]}]
        result.append(record)
    return result


def activities(days):
    import db
    result = []
    for row in db.query_activities(days):
        record = _raw(row)
        record.setdefault("id", row["id"])
        record.setdefault("start_date_local", row["date"] + "T00:00:00")
        for column, field in (("name", "name"), ("sport", "type"),
                              ("duration_sec", "moving_time"), ("tss", "icu_training_load"),
                              ("avg_power", "average_watts"), ("avg_hr", "average_heartrate")):
            if record.get(field) is None and row.get(column) is not None:
                record[field] = row[column]
        result.append(record)
    return sorted(result, key=lambda record: record.get("start_date_local", ""))
