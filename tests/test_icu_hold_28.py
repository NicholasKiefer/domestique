"""#28 step 1 + #27's duplicate guard — the calendar push stops undoing and
deleting workouts the rider moved in intervals.icu, and a swap never leaves
one workout on two days.

Hermetic like tests/test_icu_push.py (stubbed HOME, ICU only through a fake
behind ``icu_calendar_push._http``). FakeICU ignores the GET window, so a
window bug could never fail on it: ``WindowedFakeICU`` honours
oldest/newest and can drag or copy an event keeping its external_id, and
stop echoing ``filename`` (an unverified intervals.icu behaviour).

Plans are fixtures in the stored shapes: a drag onto a rest day leaves a
``moved_from:<dst>`` stub; a #27 swap leaves both days live with
``user_moved``/``moved_from`` and no stub. Nothing here depends on the
mutator in app.py.

Coverage (MASTER_DECISIONS §7): B1-B10, B12-B15, C1; C2 — at most one of our
events per workout in [today-7, today+21] unless the rider made the copy —
is checked at the end of every #28 test, and B13 (reconcile never writes the
plan) on every reconcile through ``_run``. B11 is the unchanged existing
suites.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import threading
import time
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import clock  # noqa: E402
import training_planner as tp  # noqa: E402
import icu_calendar_push as icp  # noqa: E402
from test_icu_push import (  # noqa: E402,F401  (stub is a fixture)
    stub, FakeICU, _sess, _write_plan, _apikey, _eid, STEADY_ZWO, TEMPO_ZWO,
)
from test_331_surfaces import _extract_js_function, _run_node  # noqa: E402

DASHBOARD = Path(__file__).resolve().parent.parent / "src" / "templates" / "dashboard.html"

MON = date(2026, 10, 19)                     # a Monday; the week is ahead of 2026-10-12
DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
D = {k: (MON + timedelta(days=i)).isoformat() for i, k in enumerate(DAYS)}


# ── fake ─────────────────────────────────────────────────────────────────────

class WindowedFakeICU(FakeICU):
    """FakeICU whose GET honours oldest/newest (rows with a garbled date come
    back as-is, to exercise the fail-closed path) and drops the attachment.
    Knobs: ``echo_filename``; ``drag``/``copy`` model the rider in the
    intervals.icu calendar, both keeping our external_id."""

    def __init__(self, *a, echo_filename=True, **k):
        super().__init__(*a, **k)
        self.echo_filename = echo_filename

    def __call__(self, method, path, payload=None, timeout=30.0):
        if method != "GET":
            return super().__call__(method, path, payload, timeout)
        self.calls.append((method, path, payload))
        if "GET" in self.fail:
            return self.fail["GET"]
        q = dict(p.split("=", 1) for p in path.split("?", 1)[1].split("&"))
        lo, hi = date.fromisoformat(q["oldest"]), date.fromisoformat(q["newest"])
        out = []
        for e in self.events:
            d = _day(e)
            if d is None or lo <= d <= hi:
                row = dict(e)
                row.pop("file_contents_base64", None)
                if not self.echo_filename:
                    row.pop("filename", None)
                out.append(row)
        return 200, json.dumps(out).encode()

    def _one(self, eid):
        hits = [e for e in self.events if e.get("external_id") == eid]
        assert len(hits) == 1, f"{eid}: {len(hits)} events"
        return hits[0]

    def drag(self, eid, day):
        self._one(eid)["start_date_local"] = f"{day}T00:00:00"

    def copy(self, eid, day):
        row = dict(self._one(eid), id=self._next_id, start_date_local=f"{day}T00:00:00")
        self._next_id += 1
        self.events.append(row)

    def where(self, eid):
        return sorted(e["start_date_local"][:10] for e in self.events
                      if e.get("external_id") == eid)

    def files_on(self):
        """{day: sorted workout stems} for every event of ours."""
        out = {}
        for e in self.events:
            if str(e.get("external_id") or "").startswith("domestique:") and e.get("filename"):
                out.setdefault(e["start_date_local"][:10], []).append(Path(e["filename"]).stem)
        return {d: sorted(v) for d, v in sorted(out.items())}


def _day(e):
    try:
        return date.fromisoformat(str(e.get("start_date_local") or "")[:10])
    except ValueError:
        return None


# ── plans (stored shapes) ────────────────────────────────────────────────────

def _rest(day):
    return _sess(day, zwo="", stype="rest", duration_min=0, tss_estimate=0,
                 description="Rest")


def _week(**files):
    """One Mon-Sun week. mon="steady.zwo" → a session on that file; "" → a
    fileless (unmatched) threshold session; absent → rest."""
    return [(_rest(D[k]) if k not in files
             else _sess(D[k], zwo=files[k], stype="threshold" if not files[k] else "z2"))
            for k in DAYS]


def _at(ss, day):
    return next(i for i, s in enumerate(ss) if s["day"] == day)


def _move(ss, src, dst, auto=False):
    """A drag (auto=False) or an auto-reschedule onto a rest day: the source
    becomes a stub, exactly the shape _apply_move_session stores."""
    i, j = _at(ss, src), _at(ss, dst)
    ss[j] = dict(ss[i], day=dst, user_moved=not auto, auto_moved=auto,
                 moved_from=src, status="pending")
    ss[i] = {"day": src, "day_name": ss[i]["day_name"], "session_type": "rest",
             "duration_min": 0, "tss_estimate": 0, "description": f"Moved to {dst}",
             "zwo_file": "", "zwo_name": "", "status": f"moved_from:{dst}",
             "user_moved": False, "moved_from": "", "completion_matches": None,
             "dismissed_at": ""}
    return ss


def _swap(ss, a, b):
    """#27 swap (MASTER §1.3): both land with user_moved + moved_from, no stub."""
    i, j = _at(ss, a), _at(ss, b)
    sa, sb = ss[i], ss[j]
    ss[i] = dict(sb, day=a, user_moved=True, auto_moved=False, moved_from=b)
    ss[j] = dict(sa, day=b, user_moved=True, auto_moved=False, moved_from=a)
    return ss


# ── harness ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def env(stub, freeze_clock, monkeypatch):
    freeze_clock(MON)
    _apikey(stub)
    (stub.workouts / "sweet.zwo").write_text(TEMPO_ZWO, encoding="utf-8")
    (stub.workouts / "vo2.zwo").write_text(STEADY_ZWO, encoding="utf-8")
    stub.fk = WindowedFakeICU()
    monkeypatch.setattr(icp, "_http", stub.fk)
    return stub


def _run(env):
    """One reconcile; B13: it never writes the plan and never errors here."""
    p = Path(tp.PLAN_DIR) / "current_plan.json"
    before = (p.read_bytes(), p.stat().st_mtime_ns)
    r = icp.reconcile()
    assert (p.read_bytes(), p.stat().st_mtime_ns) == before, "reconcile wrote the plan"
    assert not r.get("error") and not r.get("needs_reconnect"), r
    return r


def _seed(env, ss):
    _write_plan(ss)
    r = _run(env)
    assert r["held"] == 0
    return r


def _touched(env, since):
    """external_ids named in any POST / PUT payload after call index ``since``."""
    posted, deleted = set(), set()
    for method, _path, payload in env.fk.calls[since:]:
        if method == "POST":
            posted |= {ev["external_id"] for ev in payload}
        elif method == "PUT":
            deleted |= {ev["external_id"] for ev in payload}
    return posted, deleted


def _counts(r):
    return r["pushed"], r["updated"], r["deleted"]


def _one_event_per_session(env):
    """C2: ≤ 1 of our external_ids per workout in [today-7, today+21]. A copy
    the rider made shares the id, so it does not count twice. Fixtures give
    every session its own file."""
    today = clock.today()
    lo, hi = today - timedelta(days=7), today + timedelta(days=21)
    prefix = f"domestique:{env.pid}:"
    ids = {}
    for e in env.fk.events:
        d = _day(e)
        if str(e.get("external_id") or "").startswith(prefix) and d and lo <= d <= hi:
            ids.setdefault(Path(e.get("filename") or "").stem, set()).add(e["external_id"])
    dupes = {f: sorted(v) for f, v in ids.items() if len(v) > 1}
    assert not dupes, f"one workout on two days: {dupes}"


# ── B1-B3: a move made only in intervals.icu is left alone ───────────────────

@pytest.mark.parametrize("echo", [True, False])
def test_b1_rider_move_is_not_undone(env, echo):
    env.fk.echo_filename = echo
    _seed(env, _week(mon="sweet.zwo", wed="steady.zwo"))
    wed0 = _eid(env, D["wed"])
    env.fk.drag(wed0, D["fri"])
    for _ in range(2):                                  # and it stays that way
        mark = len(env.fk.calls)
        r = _run(env)
        posted, deleted = _touched(env, mark)
        assert wed0 not in posted and wed0 not in deleted
        assert env.fk.where(wed0) == [D["fri"]]
        assert r["held"] == 1 and _counts(r) == (0, 0, 0)
    _one_event_per_session(env)


def test_b2_moved_event_survives_its_planned_day_passing(env, freeze_clock):
    _seed(env, _week(wed="steady.zwo"))
    wed0 = _eid(env, D["wed"])
    env.fk.drag(wed0, D["fri"])
    freeze_clock(date.fromisoformat(D["thu"]))          # Wed is past; Fri ahead
    mark = len(env.fk.calls)
    r = _run(env)
    posted, deleted = _touched(env, mark)
    assert wed0 not in deleted and r["deleted"] == 0
    assert env.fk.where(wed0) == [D["fri"]]
    assert r["held"] == 1
    _one_event_per_session(env)


def test_b3_moved_to_today_is_not_pulled_back_next_day(env, freeze_clock):
    _seed(env, _week(thu="steady.zwo"))
    thu0 = _eid(env, D["thu"])
    env.fk.drag(thu0, D["mon"])                         # "ride Thursday's today"
    assert _run(env)["held"] == 1
    tue = date.fromisoformat(D["tue"])
    freeze_clock(tue)
    mark = len(env.fk.calls)
    r = _run(env)
    get = next(c for c in env.fk.calls[mark:] if c[0] == "GET")[1]
    assert f"oldest={(tue - timedelta(days=7)).isoformat()}" in get
    assert f"newest={(tue + timedelta(days=21)).isoformat()}" in get
    posted, deleted = _touched(env, mark)
    assert thu0 not in posted and thu0 not in deleted
    assert env.fk.where(thu0) == [D["mon"]]             # past day: not re-dated
    assert r["held"] == 1 and _counts(r) == (0, 0, 0)
    _one_event_per_session(env)


# ── B4: the same move made in Domestique too ends clean (grill_simple C1) ────

@pytest.mark.parametrize("echo", [True, False])
def test_b4_move_made_in_both_places_ends_with_one_event(env, echo):
    env.fk.echo_filename = echo
    ss = _week(wed="steady.zwo")
    _seed(env, ss)
    env.fk.drag(_eid(env, D["wed"]), D["fri"])
    _write_plan(_move(ss, D["wed"], D["fri"]))
    r = _run(env)
    assert r["held"] == 0 and _counts(r) == (1, 0, 1)
    assert env.fk.ids() == [_eid(env, D["fri"])]
    assert env.fk.files_on() == {D["fri"]: ["steady"]}
    assert _counts(_run(env)) == (0, 0, 0)
    _one_event_per_session(env)


# ── B5: agreed-looking, different workout (grill_data M4) ────────────────────

def test_b5_swap_then_stack_in_icu_is_held_not_reverted(env):
    ss = _week(thu="steady.zwo", fri="tempo_alt.zwo")
    _seed(env, ss)
    _write_plan(_swap(ss, D["thu"], D["fri"]))
    assert _counts(_run(env)) == (0, 2, 0)              # THU:0 tempo, FRI:0 steady
    thu0 = _eid(env, D["thu"])
    env.fk.drag(thu0, D["fri"])                         # rider stacks the tempo on Fri
    mark = len(env.fk.calls)
    r = _run(env)
    posted, deleted = _touched(env, mark)
    assert thu0 not in posted and thu0 not in deleted
    assert env.fk.where(thu0) == [D["fri"]]
    assert env.fk.files_on() == {D["fri"]: ["steady", "tempo_alt"]}
    assert r["held"] == 1 and _counts(r) == (0, 0, 0)
    _one_event_per_session(env)


# ── B6: one event per session (grill_cal C-1, prototype R1) ──────────────────

@pytest.mark.parametrize("echo", [True, False])
def test_b6_auto_reschedule_after_rider_move_pushes_no_second_copy(env, freeze_clock, echo):
    env.fk.echo_filename = echo
    ss = _week(mon="sweet.zwo", wed="steady.zwo")
    _seed(env, ss)
    wed0 = _eid(env, D["wed"])
    env.fk.drag(wed0, D["thu"])                         # rider: Wed's ride on Thu
    assert _run(env)["held"] == 1
    freeze_clock(date.fromisoformat(D["thu"]))
    ss[_at(ss, D["wed"])]["status"] = "missed"
    _write_plan(_move(ss, D["wed"], D["sat"], auto=True))  # adapt re-owes it Sat
    mark = len(env.fk.calls)
    r = _run(env)
    posted, deleted = _touched(env, mark)
    assert _eid(env, D["sat"]) not in posted
    assert wed0 not in posted and wed0 not in deleted
    assert env.fk.where(wed0) == [D["thu"]]
    assert D["sat"] not in env.fk.files_on()
    assert r["held"] == 1
    _one_event_per_session(env)


def test_b6_chain_of_moves_is_followed(env):
    """Wed → Sat (auto) → Sun (drag): the rider's Wed event on Thu still
    stands in for the session, wherever the chain ends."""
    ss = _week(mon="sweet.zwo", wed="steady.zwo")
    _seed(env, ss)
    env.fk.drag(_eid(env, D["wed"]), D["thu"])
    _move(ss, D["wed"], D["sat"], auto=True)
    _write_plan(_move(ss, D["sat"], D["sun"]))
    mark = len(env.fk.calls)
    r = _run(env)
    posted, _ = _touched(env, mark)
    assert _eid(env, D["sun"]) not in posted and _eid(env, D["sat"]) not in posted
    assert env.fk.files_on() == {D["mon"]: ["sweet"], D["thu"]: ["steady"]}
    assert r["held"] == 1
    _one_event_per_session(env)


def test_b6_session_on_held_slot_after_swap_is_not_pushed_twice(env):
    """#27 × #28 (grill_cal S8): the rider moved WED:0 (steady) to Fri, then
    swapped Wed↔Thu in Domestique. The steady now lives on Thu; the rider's
    Fri event stands in for it, so THU:0 is not pushed with steady."""
    ss = _week(wed="steady.zwo", thu="tempo_alt.zwo")
    _seed(env, ss)
    env.fk.drag(_eid(env, D["wed"]), D["fri"])
    _write_plan(_swap(ss, D["wed"], D["thu"]))
    r = _run(env)
    assert r["held"] == 1
    # Steady only where the rider put it. The tempo now planned on Wed is not
    # pushed while WED:0 is held (no bumped id): missing, never doubled
    # (grill_simple M2 — learning the move is #28 step 2).
    assert env.fk.files_on() == {D["fri"]: ["steady"]}
    _one_event_per_session(env)


# ── B7: swaps ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("echo", [True, False])
def test_b7_swap_in_icu_only_holds_both(env, echo):
    env.fk.echo_filename = echo
    _seed(env, _week(wed="steady.zwo", thu="tempo_alt.zwo"))
    wed0, thu0 = _eid(env, D["wed"]), _eid(env, D["thu"])
    env.fk.drag(wed0, D["thu"])
    env.fk.drag(thu0, D["wed"])
    mark = len(env.fk.calls)
    r = _run(env)
    posted, deleted = _touched(env, mark)
    assert not ({wed0, thu0} & (posted | deleted))
    assert env.fk.files_on() == {D["wed"]: ["tempo_alt"], D["thu"]: ["steady"]}
    assert r["held"] == 2 and _counts(r) == (0, 0, 0)
    _one_event_per_session(env)


@pytest.mark.parametrize("echo", [True, False])
def test_b7_swap_in_both_places_is_clean(env, echo):
    env.fk.echo_filename = echo
    ss = _week(wed="steady.zwo", thu="tempo_alt.zwo")
    _seed(env, ss)
    env.fk.drag(_eid(env, D["wed"]), D["thu"])
    env.fk.drag(_eid(env, D["thu"]), D["wed"])
    _write_plan(_swap(ss, D["wed"], D["thu"]))
    r = _run(env)
    assert r["held"] == 0 and _counts(r) == (0, 2, 0)
    assert env.fk.files_on() == {D["wed"]: ["tempo_alt"], D["thu"]: ["steady"]}
    assert sorted(env.fk.where(_eid(env, D["wed"]))) == [D["wed"]]
    assert _counts(_run(env)) == (0, 0, 0)
    _one_event_per_session(env)


def test_swap_in_domestique_only_updates_both_in_place(env):
    """#27 baseline: both buildable → (0, 2, 0), ids unchanged, content swapped."""
    ss = _week(wed="steady.zwo", thu="tempo_alt.zwo")
    _seed(env, ss)
    _write_plan(_swap(ss, D["wed"], D["thu"]))
    r = _run(env)
    assert r["held"] == 0 and _counts(r) == (0, 2, 0)
    assert env.fk.files_on() == {D["wed"]: ["tempo_alt"], D["thu"]: ["steady"]}
    _one_event_per_session(env)


# ── B8: a copy that keeps our id ─────────────────────────────────────────────

def test_b8_copy_with_one_moved_copy_freezes_the_id(env):
    _seed(env, _week(wed="steady.zwo"))
    wed0 = _eid(env, D["wed"])
    env.fk.copy(wed0, D["fri"])
    mark = len(env.fk.calls)
    r = _run(env)
    posted, deleted = _touched(env, mark)
    assert wed0 not in posted and wed0 not in deleted
    assert env.fk.where(wed0) == [D["wed"], D["fri"]]
    assert r["held"] == 1
    _one_event_per_session(env)


def test_b8_copy_on_the_same_day_is_legacy(env):
    _seed(env, _week(wed="steady.zwo"))
    wed0 = _eid(env, D["wed"])
    env.fk.copy(wed0, D["wed"])
    mark = len(env.fk.calls)
    r = _run(env)
    posted, _ = _touched(env, mark)
    assert wed0 in posted and r["held"] == 0           # upserted as before
    _one_event_per_session(env)


# ── B9: foreign / manual / garbled ids and dates: unchanged behaviour ────────

def test_b9_foreign_manual_and_unparseable_unchanged(env):
    _seed(env, _week(wed="steady.zwo"))
    wed0 = _eid(env, D["wed"])
    foreign = f"domestique:other-profile:{D['wed']}:0"
    manual = f"domestique-manual:{env.pid}:abcd1234"
    loose = f"{wed0}:x"                                 # our prefix, not our id shape
    env.fk.events += [
        {"id": 1, "external_id": foreign, "start_date_local": f"{D['fri']}T00:00:00",
         "name": "other install", "filename": "other.zwo", "category": "WORKOUT"},
        {"id": 2, "external_id": manual, "start_date_local": f"{D['fri']}T00:00:00",
         "name": "manual", "filename": "manual.zwo", "category": "WORKOUT"},
        {"id": 3, "external_id": loose, "start_date_local": f"{D['fri']}T00:00:00",
         "name": "loose", "filename": "loose.zwo", "category": "WORKOUT"},
        {"id": 4, "external_id": _eid(env, D["thu"]), "start_date_local": "garbage",
         "name": "garbled", "filename": "garbled.zwo", "category": "WORKOUT"},
    ]
    env.fk._one(wed0)["start_date_local"] = "garbage"   # garbled date on a live slot
    mark = len(env.fk.calls)
    with mock.patch.object(icp._log, "warning") as warn:
        r = _run(env)
    posted, deleted = _touched(env, mark)
    assert r["held"] == 0
    assert not ({foreign, manual, _eid(env, D["thu"])} & (posted | deleted))
    assert {foreign, manual, _eid(env, D["thu"])} <= set(env.fk.ids())
    assert any("foreign" in str(c) for c in warn.call_args_list)      # G-B
    assert wed0 in posted and env.fk.where(wed0) == [D["wed"]]         # legacy upsert
    assert loose in deleted                                            # legacy sweep
    _one_event_per_session(env)


# ── B10: beyond the horizon and in the past: never deleted, never re-dated ───

def test_b10_beyond_horizon_and_past_events_untouched(env):
    _seed(env, _week(wed="steady.zwo"))
    t = clock.today()
    rows = {
        _eid(env, (t + timedelta(days=16)).isoformat()): t + timedelta(days=16),  # planner push
        _eid(env, (t + timedelta(days=10)).isoformat()): t + timedelta(days=18),  # moved past the horizon
        _eid(env, (t - timedelta(days=3)).isoformat()): t - timedelta(days=3),    # ridden day
        _eid(env, (t - timedelta(days=2)).isoformat()): t - timedelta(days=5),    # moved within the past
    }
    for i, (eid, d) in enumerate(rows.items()):
        env.fk.events.append({"id": 50 + i, "external_id": eid, "category": "WORKOUT",
                              "start_date_local": f"{d.isoformat()}T00:00:00",
                              "name": f"r{i}", "filename": f"r{i}.zwo"})
    mark = len(env.fk.calls)
    r = _run(env)
    get = next(c for c in env.fk.calls[mark:] if c[0] == "GET")[1]
    assert f"newest={(t + timedelta(days=21)).isoformat()}" in get   # they were read
    posted, deleted = _touched(env, mark)
    assert not (set(rows) & (posted | deleted))
    assert r["deleted"] == 0 and r["held"] == 2
    for eid, d in rows.items():
        assert env.fk.where(eid) == [d.isoformat()]
    _one_event_per_session(env)


# ── B12: sweep_all keeps its window and still removes everything ours ────────

def test_b12_sweep_all_unchanged(env):
    _seed(env, _week(wed="steady.zwo", fri="tempo_alt.zwo"))
    env.fk.drag(_eid(env, D["wed"]), D["thu"])          # a held move goes too
    t = clock.today()
    beyond = _eid(env, (t + timedelta(days=16)).isoformat())
    env.fk.events.append({"id": 77, "external_id": beyond, "category": "WORKOUT",
                          "start_date_local": f"{(t + timedelta(days=16)).isoformat()}T00:00:00",
                          "name": "beyond", "filename": "beyond.zwo"})
    mark = len(env.fk.calls)
    r = icp.sweep_all()
    get = next(c for c in env.fk.calls[mark:] if c[0] == "GET")[1]
    assert get.endswith(f"events?oldest={t.isoformat()}"
                        f"&newest={(t + timedelta(days=14)).isoformat()}")
    assert r["deleted"] == 2 and env.fk.ids() == [beyond]
    assert "held" not in r


# ── B13: never writes the plan, never raises ─────────────────────────────────

def test_b13_corrupt_chain_and_internal_failure_never_raise(env, monkeypatch):
    ss = _week(mon="sweet.zwo", wed="steady.zwo")
    _seed(env, ss)
    env.fk.drag(_eid(env, D["wed"]), D["fri"])
    # Corrupt plan: Wed → Thu → Wed stubs (a cycle); resolution must stop.
    _move(ss, D["wed"], D["thu"])
    ss[_at(ss, D["thu"])] = dict(ss[_at(ss, D["wed"])], day=D["thu"],
                                 status=f"moved_from:{D['wed']}")
    _write_plan(ss)
    r = _run(env)                                       # plan bytes + mtime unchanged
    assert r["held"] == 1 and env.fk.where(_eid(env, D["wed"])) == [D["fri"]]

    def boom(*_a, **_k):
        raise RuntimeError("hold logic exploded")
    monkeypatch.setattr(icp, "_held_ids", boom)
    mark = len(env.fk.calls)
    r = icp.reconcile()
    assert r["error"] == "internal:RuntimeError"
    assert [c[0] for c in env.fk.calls[mark:]] == ["GET"]   # no POST, no PUT


def test_b13_get_failure_pushes_and_deletes_nothing(env):
    _seed(env, _week(wed="steady.zwo"))
    env.fk.drag(_eid(env, D["wed"]), D["fri"])
    _write_plan(_week(wed="steady.zwo", sat="tempo_alt.zwo"))
    env.fk.fail["GET"] = (500, b"down")
    mark = len(env.fk.calls)
    r = icp.reconcile()
    assert r["error"] == "http_500"
    assert [c[0] for c in env.fk.calls[mark:]] == ["GET"]


# ── B14: the toast says what was left alone ──────────────────────────────────

@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_b14_push_toast_names_held_moves():
    src = DASHBOARD.read_text(encoding="utf-8")
    harness = _extract_js_function(src, "icuPushToastFromResult") + """
const seen = [];
global.showToast = (m) => seen.push(m);
const v = 'Pushed to intervals.icu';
icuPushToastFromResult({pushed: 0, updated: 0, deleted: 0, skipped: [], held: 2}, v);
icuPushToastFromResult({pushed: 1, updated: 0, deleted: 0, skipped: [{}], held: 1}, v);
icuPushToastFromResult({pushed: 0, updated: 0, deleted: 0, skipped: [], held: 0}, v);
icuPushToastFromResult({pushed: 0, updated: 0, deleted: 2, skipped: []}, 'Calendar sync off — cleanup');
const want = [
  'Pushed to intervals.icu: calendar already up to date · 2 left where you moved it in intervals.icu',
  'Pushed to intervals.icu: 1 new · 1 skipped · 1 left where you moved it in intervals.icu',
  'Pushed to intervals.icu: calendar already up to date',
  'Calendar sync off — cleanup: 2 removed',
];
if (JSON.stringify(seen) !== JSON.stringify(want)) throw new Error(JSON.stringify(seen));
console.log('OK');
"""
    _run_node(harness)


# ── B15: one reconcile at a time ─────────────────────────────────────────────

def test_b15_second_reconcile_waits_for_the_first(env, monkeypatch):
    _write_plan(_week(wed="steady.zwo"))
    fk, calls = env.fk, []
    in_post, release = threading.Event(), threading.Event()

    def transport(method, path, payload=None, timeout=30.0):
        calls.append((threading.current_thread().name, method))
        if method == "POST" and threading.current_thread().name == "A":
            in_post.set()
            release.wait(10)
        return fk(method, path, payload, timeout)

    monkeypatch.setattr(icp, "_http", transport)
    out = {}
    a = threading.Thread(target=lambda: out.setdefault("A", icp.reconcile()), name="A")
    b = threading.Thread(target=lambda: out.setdefault("B", icp.reconcile()), name="B")
    a.start()
    assert in_post.wait(10)
    b.start()
    time.sleep(0.3)
    assert not [c for c in calls if c[0] == "B"]        # B is waiting on the lock
    release.set()
    a.join(10)
    b.join(10)
    assert calls == [("A", "GET"), ("A", "POST"), ("B", "GET"), ("B", "POST")]
    assert _counts(out["A"]) == (1, 0, 0) and _counts(out["B"]) == (0, 0, 0)


def test_b15_busy_after_the_timeout(env, monkeypatch):
    _write_plan(_week(wed="steady.zwo"))
    monkeypatch.setattr(icp, "_RECONCILE_LOCK_TIMEOUT_S", 0.05)
    assert icp._RECONCILE_LOCK.acquire(timeout=1)
    try:
        assert icp.reconcile()["error"] == "busy"
        assert icp.sweep_all()["error"] == "busy"
    finally:
        icp._RECONCILE_LOCK.release()
    assert env.fk.calls == []
    assert icp.reconcile()["pushed"] == 1               # free again


# ── C1 (#27, MASTER §4.1): an unbuildable swap partner never duplicates ──────

def test_c1_swap_with_fileless_partner_leaves_one_copy(env):
    ss = _week(wed="steady.zwo", thu="")
    _seed(env, ss)                                      # WED:0 steady; Thu unmatched
    _write_plan(_swap(ss, D["wed"], D["thu"]))
    r = _run(env)
    assert {"day": D["wed"], "reason": "unmatched"} in r["skipped"]
    assert _counts(r) == (1, 0, 1)
    assert env.fk.files_on() == {D["thu"]: ["steady"]}
    _one_event_per_session(env)


def test_c1_swap_with_missing_file_partner_puts_nothing_on_the_wrong_day(env):
    ss = _week(wed="steady.zwo", thu="tempo_alt.zwo")
    _seed(env, ss)
    _write_plan(_swap(ss, D["wed"], D["thu"]))
    (env.workouts / "tempo_alt.zwo").rename(env.workouts / "tempo_alt.bak")
    r = _run(env)
    assert {"day": D["wed"], "reason": "file_missing"} in r["skipped"]
    assert _counts(r) == (0, 1, 1)
    assert env.fk.files_on() == {D["thu"]: ["steady"]}
    _one_event_per_session(env)


def test_c1_hr_swap_with_trailing_open_partner_leaves_one_copy(env):
    env.pm._athlete.update({"target_mode": "hr", "lthr": 160, "max_hr": 185})
    ss = _week(wed="steady.zwo", thu="sprint_end.zwo")
    _seed(env, ss)                                      # WED:0 steady.fit; Thu trailing_open
    assert env.fk.files_on() == {D["wed"]: ["steady"]}
    _write_plan(_swap(ss, D["wed"], D["thu"]))
    r = _run(env)
    assert {"day": D["wed"], "reason": "trailing_open"} in r["skipped"]
    assert env.fk.files_on() == {D["thu"]: ["steady"]}
    _one_event_per_session(env)


@pytest.mark.parametrize("echo", [True, False])
def test_c1_library_outage_on_unmoved_session_keeps_its_event(env, echo):
    env.fk.echo_filename = echo
    _seed(env, _week(wed="steady.zwo"))
    (env.workouts / "steady.zwo").rename(env.workouts / "steady.bak")
    r = _run(env)
    assert {"day": D["wed"], "reason": "file_missing"} in r["skipped"]
    assert r["deleted"] == 0 and env.fk.files_on() == {D["wed"]: ["steady"]}


def test_c1_moved_session_keeps_its_own_event_through_a_build_failure(env):
    """Same workout at the id (steady.fit vs steady.zwo compare by stem):
    a session pushed after its move keeps its event when lthr breaks."""
    env.pm._athlete.update({"target_mode": "hr", "lthr": 160, "max_hr": 185})
    _seed(env, _move(_week(wed="steady.zwo"), D["wed"], D["fri"]))
    assert env.fk.files_on() == {D["fri"]: ["steady"]}
    env.pm._athlete.update({"max_hr": 150})             # lthr invariant broken
    r = _run(env)
    assert r.get("needs_lthr") is True
    assert r["deleted"] == 0 and env.fk.files_on() == {D["fri"]: ["steady"]}


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
