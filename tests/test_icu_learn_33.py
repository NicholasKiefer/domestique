"""#33 (#28 step 2) — a plain move the rider makes in the intervals.icu
calendar is learned into the plan, as if dragged in Domestique.

Learned: one event under its id, both days today or later in one week, from
a day holding that one pending workout onto a rest/empty/vacated day that is
not unavailable and not a race. The event is then re-keyed by the agreed-move
rule in the same run. Everything else stays held (#28 step 1). Never learned
when most of our events look shifted (a date-reading problem, not moves).
"""
from __future__ import annotations

import json
import shutil
from datetime import date, timedelta
from pathlib import Path

import pytest

import clock
import icu_calendar_push as icp
import training_planner as tp
from test_icu_push import stub, _write_plan, _apikey, _eid, TEMPO_ZWO, STEADY_ZWO  # noqa: F401
from test_icu_hold_28 import (  # noqa: E402
    WindowedFakeICU, MON, D, _week, _move, _one_event_per_session, _counts, _at,
)
from test_331_surfaces import _extract_js_function, _run_node

DASHBOARD = Path(__file__).resolve().parent.parent / "src" / "templates" / "dashboard.html"


@pytest.fixture()
def env(stub, freeze_clock, monkeypatch):
    freeze_clock(MON)
    _apikey(stub)
    (stub.workouts / "sweet.zwo").write_text(TEMPO_ZWO, encoding="utf-8")
    (stub.workouts / "vo2.zwo").write_text(STEADY_ZWO, encoding="utf-8")
    stub.fk = WindowedFakeICU()
    monkeypatch.setattr(icp, "_http", stub.fk)
    return stub


def _plan():
    return json.loads((Path(tp.PLAN_DIR) / "current_plan.json").read_text())


def _on(day):
    return [s for w in _plan()["weeks"] for s in w["sessions"] if s["day"] == day]


def _seed(env, ss):
    _write_plan(ss)
    r = icp.reconcile()
    assert not r.get("error") and r["learned"] == [] and r["held"] == 0, r


@pytest.mark.parametrize("echo", [True, False])
def test_a_drag_onto_a_rest_day_is_learned_and_the_event_rekeyed(env, echo):
    env.fk.echo_filename = echo
    _seed(env, _week(mon="sweet.zwo", wed="steady.zwo"))
    wed0, fri0 = _eid(env, D["wed"]), _eid(env, D["fri"])
    env.fk.drag(wed0, D["fri"])
    r = icp.reconcile()
    assert [(m["from"], m["to"]) for m in r["learned"]] == [(D["wed"], D["fri"])]
    assert r["held"] == 0 and not r.get("error")
    fri, = _on(D["fri"])
    assert (fri["zwo_file"], fri["user_moved"], fri["moved_from"]) == ("steady.zwo", True, D["wed"])
    wed, = _on(D["wed"])
    assert wed["status"] == f"moved_from:{D['fri']}"
    assert env.fk.where(fri0) == [D["fri"]] and env.fk.where(wed0) == []
    assert env.fk.files_on() == {D["mon"]: ["sweet"], D["fri"]: ["steady"]}
    before = _plan()
    r2 = icp.reconcile()                                  # settled: nothing moves
    assert r2["learned"] == [] and _counts(r2) == (0, 0, 0) and _plan() == before
    _one_event_per_session(env)


def test_a_drag_to_today_is_learned(env):
    _seed(env, _week(thu="steady.zwo"))
    env.fk.drag(_eid(env, D["thu"]), D["mon"])            # MON is today
    r = icp.reconcile()
    assert [(m["from"], m["to"]) for m in r["learned"]] == [(D["thu"], D["mon"])]
    assert env.fk.files_on() == {D["mon"]: ["steady"]}


@pytest.mark.parametrize("why,setup", [
    ("onto a training day", lambda env: env.fk.drag(_eid(env, D["wed"]), D["thu"])),
    ("into next week", lambda env: env.fk.drag(_eid(env, D["wed"]), (MON + timedelta(days=9)).isoformat())),
    ("a copy, two events one id", lambda env: env.fk.copy(_eid(env, D["wed"]), D["fri"])),
])
def test_moves_that_are_not_plain_stay_held_and_the_plan_untouched(env, why, setup):
    _seed(env, _week(wed="steady.zwo", thu="sweet.zwo"))
    before = _plan()
    setup(env)
    r = icp.reconcile()
    assert r["learned"] == [] and _plan() == before, why
    assert r["held"] == 1, why
    if "copy" not in why:
        _one_event_per_session(env)


def test_a_move_into_the_past_is_not_learned(env, freeze_clock):
    _seed(env, _week(wed="steady.zwo"))
    env.fk.drag(_eid(env, D["wed"]), (MON - timedelta(days=1)).isoformat())
    before = _plan()
    r = icp.reconcile()
    assert r["learned"] == [] and _plan() == before


@pytest.mark.parametrize("mark", ["zero_hours", "period", "race"])
def test_an_unavailable_or_race_day_is_not_learned(env, mark):
    ss = _week(wed="steady.zwo")
    _seed(env, ss)
    plan = _plan()
    if mark == "zero_hours":
        plan["availability"] = {D["fri"]: 0}
    elif mark == "period":
        plan["unavailable_periods"] = [{"start": D["thu"], "end": D["sat"], "type": "holiday"}]
    else:
        fri = next(s for w in plan["weeks"] for s in w["sessions"] if s["day"] == D["fri"])
        fri["is_race"] = True
    tp.atomic_write_plan(Path(tp.PLAN_DIR) / "current_plan.json", plan)
    env.fk.drag(_eid(env, D["wed"]), D["fri"])
    before = _plan()
    r = icp.reconcile()
    assert r["learned"] == [] and _plan() == before and r["held"] == 1


def test_a_day_domestique_changed_after_the_move_is_not_learned(env):
    """Owner rule: Domestique's own later change of that day wins."""
    ss = _week(wed="steady.zwo")
    _seed(env, ss)
    env.fk.drag(_eid(env, D["wed"]), D["fri"])
    ss[_at(ss, D["wed"])]["zwo_file"] = "sweet.zwo"       # a different workout now
    _write_plan(ss)
    r = icp.reconcile()
    assert r["learned"] == []
    assert _on(D["wed"])[0]["zwo_file"] == "sweet.zwo"


def test_most_events_shifted_means_a_date_problem_and_nothing_is_learned(env):
    _seed(env, _week(mon="sweet.zwo", wed="steady.zwo", fri="vo2.zwo"))
    for day, nxt in (("mon", "tue"), ("wed", "thu"), ("fri", "sat")):   # each onto a rest day
        env.fk.drag(_eid(env, D[day]), D[nxt])
    before = _plan()
    r = icp.reconcile()
    assert r["learned"] == [] and _plan() == before


def test_a_skipped_workout_moved_in_icu_is_not_learned(env):
    ss = _week(wed="steady.zwo")
    _seed(env, ss)
    env.fk.drag(_eid(env, D["wed"]), D["fri"])
    ss[_at(ss, D["wed"])]["status"] = "dismissed"
    _write_plan(ss)
    assert icp.reconcile()["learned"] == []


def test_the_move_learned_is_pinned_like_a_drag(env):
    """It keeps its length when the day's hours change (#27 O4) because it
    is the rider's move; the auto-reschedule never moves it back."""
    _seed(env, _week(wed="steady.zwo"))
    env.fk.drag(_eid(env, D["wed"]), D["fri"])
    icp.reconcile()
    fri, = _on(D["fri"])
    assert fri["user_moved"] is True and not fri.get("auto_moved")


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_the_push_toast_says_what_was_learned():
    src = DASHBOARD.read_text(encoding="utf-8")
    harness = _extract_js_function(src, "icuPushToastFromResult") + """
const seen = [];
global.showToast = (m) => seen.push(m);
icuPushToastFromResult({pushed: 1, updated: 0, deleted: 1, skipped: [], held: 0,
                        learned: [{from: '2026-10-21', to: '2026-10-23', name: 'Z2'}]}, 'Pushed to intervals.icu');
const want = ['Pushed to intervals.icu: 1 new · 1 removed · 1 workout moved in your plan to match intervals.icu'];
if (JSON.stringify(seen) !== JSON.stringify(want)) throw new Error(JSON.stringify(seen));
console.log('OK');
"""
    _run_node(harness)
