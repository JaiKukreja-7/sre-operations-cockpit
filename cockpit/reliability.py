import math
from datetime import datetime, timezone
from cockpit.models import CheckConfig, DISPATCH_GRACE_SECONDS, Policy


def timestamp(value):
    return None if value is None else datetime.fromtimestamp(value, timezone.utc).isoformat()


def calculate(good, bad, unknown, eligible, target, pending=0):
    observed = good + bad
    allowed = observed * (1 - target)
    return {
        "good": good, "bad": bad, "unknown": unknown, "pending": pending,
        "eligible_slots": eligible, "observed_events": observed,
        "unrecorded_slots": max(0, eligible - observed - unknown - pending),
        "sli": good / observed if observed else None,
        "allowed_bad_events": allowed,
        "remaining_budget": allowed - bad,
        "burn_rate": (bad / observed) / (1 - target) if observed else None,
        "sample_coverage": observed / eligible if eligible else None,
    }


def _window(conn, check_id, start, end, target):
    schedules = conn.execute("SELECT * FROM schedules WHERE check_id=?", (check_id,)).fetchall()
    eligible = 0
    overdue_eligible = 0
    cutoff = end - DISPATCH_GRACE_SECONDS
    for schedule in schedules:
        interval = CheckConfig.model_validate_json(schedule["config"]).interval_seconds
        lower = max(start, schedule["start"])
        upper = min(end, schedule["end"] if schedule["end"] is not None else end)
        if upper <= lower:
            continue
        # Slots start + k*interval; both schedule and query use [start, end).
        first = max(0, math.ceil((lower - schedule["start"]) / interval))
        stop = max(0, math.ceil((upper - schedule["start"]) / interval))
        eligible += max(0, stop - first)
        # A retired, unclaimed slot can no longer be dispatched, even when its
        # ordinary grace period has not elapsed. Claimed rows are subtracted below.
        overdue_upper = upper if schedule["end"] is not None and schedule["end"] <= end else min(upper, cutoff)
        overdue_stop = max(0, math.ceil((overdue_upper - schedule["start"]) / interval))
        overdue_eligible += max(0, overdue_stop - first)
    counts = {"GOOD": 0, "BAD": 0, "UNKNOWN": 0, "PENDING": 0}
    for row in conn.execute("""SELECT outcome,COUNT(*) AS n FROM results
        WHERE check_id=? AND scheduled_at>=? AND scheduled_at<? GROUP BY outcome""", (check_id, start, end)):
        counts[row["outcome"]] = row["n"]
    overdue_recorded = conn.execute("""SELECT COUNT(*) FROM results r
        JOIN schedules s ON s.id=r.schedule_id
        WHERE r.check_id=? AND r.scheduled_at>=? AND r.scheduled_at<?
        AND (r.scheduled_at<? OR (s.end IS NOT NULL AND s.end<=?))""",
        (check_id, start, end, cutoff, end)).fetchone()[0]
    inferred_unknown = max(0, overdue_eligible - overdue_recorded)
    result = calculate(counts["GOOD"], counts["BAD"], counts["UNKNOWN"] + inferred_unknown, eligible,
                       target, counts["PENDING"])
    result["recorded_unknown"] = counts["UNKNOWN"]
    result["inferred_unknown"] = inferred_unknown
    result["awaiting_slots"] = result["unrecorded_slots"]
    result["unrecorded_slots"] += inferred_unknown
    return dict(window_start=timestamp(start), window_end=timestamp(end), **result)


def window(store, check_id, start, end, target):
    with store.connect() as conn:
        conn.execute("BEGIN")
        return _window(conn, check_id, start, end, target)


def summary(store, check_id, policy_name, now):
    # The policy and all windows share a snapshot, even while probes finish or
    # configurations change in another process. WAL permits concurrent writers.
    with store.connect() as conn:
        conn.execute("BEGIN")
        row = conn.execute("SELECT config FROM policies WHERE name=?", (policy_name,)).fetchone()
        if row is None:
            raise KeyError(policy_name)
        policy = Policy.model_validate_json(row["config"])
        main = _window(conn, check_id, now - policy.window_seconds, now, policy.slo_target)
        short = _window(conn, check_id, now - policy.short_window_seconds, now, policy.slo_target)
        long = _window(conn, check_id, now - policy.long_window_seconds, now, policy.slo_target)
    enough = (short["observed_events"] >= policy.short_min_samples
              and long["observed_events"] >= policy.long_min_samples)
    triggered = enough and all(w["burn_rate"] is not None and
                              w["burn_rate"] >= policy.alert_burn_threshold for w in (short, long))
    return {"check_id": check_id, "policy_name": policy_name, "policy": policy.model_dump(),
            "generated_at": timestamp(now), "slot_boundary": "[start, end)",
            "dispatch_grace_seconds": DISPATCH_GRACE_SECONDS,
            "summary": main, "alert": {"state": "FIRING" if triggered else
                "OK" if enough else "INSUFFICIENT_DATA", "short": short, "long": long,
                "minimum_samples_met": enough}}
