import pytest
from cockpit.db import Store
from cockpit.models import CheckConfig
from cockpit.reliability import calculate, summary, window


def test_budget_math_and_negative_budget():
    values = calculate(8, 2, 3, 13, .9)
    assert values['sli'] == .8
    assert values['allowed_bad_events'] == pytest.approx(1)
    assert values['remaining_budget'] == pytest.approx(-1)
    assert values['burn_rate'] == pytest.approx(2)
    assert values['sample_coverage'] == pytest.approx(10 / 13)


def test_no_observations_and_all_unknown():
    for eligible in (0, 10):
        values = calculate(0, 0, eligible, eligible, .99)
        assert values['sli'] is None
        assert values['burn_rate'] is None
        assert values['remaining_budget'] == 0
        assert values['sample_coverage'] == (0 if eligible else None)


def test_half_open_windows_and_schedule_history(tmp_path):
    store = Store(tmp_path / 'test.db')
    store.initialize(now=100)
    # Old schedule has slots 100,105,110. New schedule has 112,122.
    store.update_check(1, CheckConfig(interval_seconds=10), now=112)
    assert window(store, 1, 100, 123, .95)['eligible_slots'] == 5
    assert window(store, 1, 105, 112, .95)['eligible_slots'] == 2
    assert window(store, 1, 112, 122, .95)['eligible_slots'] == 1
    store.update_check(1, CheckConfig(interval_seconds=10, enabled=False), now=123)
    assert window(store, 1, 100, 200, .95)['eligible_slots'] == 5
    assert window(store, 1, 0, 99, .95)['eligible_slots'] == 0


def test_policy_separation_and_minimum_counts(tmp_path):
    store = Store(tmp_path / 'test.db')
    store.initialize(now=100)
    demo = summary(store, 1, 'demo', 111)
    report = summary(store, 1, 'thirty_day', 111)
    assert demo['policy']['window_seconds'] == 300
    assert report['policy']['window_seconds'] == 30 * 86400
    assert demo['summary']['eligible_slots'] == 3
    assert demo['summary']['unrecorded_slots'] == 3
    assert demo['summary']['unknown'] == 2
    assert demo['summary']['inferred_unknown'] == 2
    assert demo['summary']['awaiting_slots'] == 1
    assert demo['alert']['state'] == 'INSUFFICIENT_DATA'


def test_inferred_unknown_is_not_double_counted_after_backfill(tmp_path):
    store = Store(tmp_path / 'test.db')
    store.initialize(now=100)
    before = window(store, 1, 100, 116, .95)
    assert before['unknown'] == 3  # 100,105,110; slot 115 is still in grace.
    assert before['recorded_unknown'] == 0
    assert before['sample_coverage'] == 0
    for _ in range(3):
        store.claim_next(116)
    after = window(store, 1, 100, 116, .95)
    assert after['unknown'] == before['unknown']
    assert after['recorded_unknown'] == 3
    assert after['inferred_unknown'] == 0
    assert after['awaiting_slots'] == 1


def test_alert_requires_both_windows_and_minimum_samples(tmp_path):
    store = Store(tmp_path / 'test.db')
    store.initialize(now=100)
    for slot in range(100, 220, 5):
        job = store.claim_next(slot)
        store.complete(job['result_id'], dict(outcome='BAD', http_status=500,
                       latency_ms=1, failure_reason='HTTP 500'), now=slot + .1)
    result = summary(store, 1, 'demo', 220)
    assert result['alert']['state'] == 'FIRING'
    assert result['summary']['remaining_budget'] < 0
    # Short window recovers even though the long window retains many failures.
    for slot in range(220, 250, 5):
        job = store.claim_next(slot)
        store.complete(job['result_id'], dict(outcome='GOOD', http_status=200,
                       latency_ms=1, failure_reason=None), now=slot + .1)
    assert summary(store, 1, 'demo', 250)['alert']['state'] == 'OK'


def test_summary_uses_one_snapshot_during_concurrent_completion(tmp_path, monkeypatch):
    import cockpit.reliability as reliability
    store = Store(tmp_path / 'test.db')
    store.initialize(now=100)
    original = reliability._window
    calls = []

    def window_with_concurrent_writer(conn, *args):
        values = original(conn, *args)
        calls.append(values)
        if len(calls) == 1:
            job = store.claim_next(100)
            store.complete(job['result_id'], dict(outcome='GOOD', http_status=200,
                           latency_ms=1, failure_reason=None), now=100.1)
        return values

    monkeypatch.setattr(reliability, '_window', window_with_concurrent_writer)
    result = reliability.summary(store, 1, 'demo', 101)
    assert result['summary']['observed_events'] == 0
    assert result['alert']['short']['observed_events'] == 0
    assert result['alert']['long']['observed_events'] == 0
    monkeypatch.setattr(reliability, '_window', original)
    assert reliability.summary(store, 1, 'demo', 101)['summary']['observed_events'] == 1


def test_equal_timestamp_disable_keeps_claimed_slot_eligible(tmp_path):
    store = Store(tmp_path / 'test.db')
    store.initialize(now=100)
    job = store.claim_next(100)
    store.complete(job['result_id'], dict(outcome='GOOD', http_status=200,
                   latency_ms=1, failure_reason=None), now=100.1)
    store.update_check(1, CheckConfig(enabled=False), now=100)
    values = window(store, 1, 99, 101, .95)
    assert values['eligible_slots'] == values['observed_events'] == 1
    assert values['sample_coverage'] == 1


def test_clock_rollback_does_not_overlap_configuration_epochs(tmp_path):
    store = Store(tmp_path / 'test.db')
    store.initialize(now=100)
    store.update_check(1, CheckConfig(interval_seconds=10), now=110)
    store.update_check(1, CheckConfig(interval_seconds=5), now=105)
    # Old slots 100,105; replacement slots 110,115. No retroactive slot at 105.
    assert window(store, 1, 99, 116, .95)['eligible_slots'] == 4
    with store.connect() as conn:
        schedules = conn.execute('SELECT start,end FROM schedules ORDER BY id').fetchall()
    assert all(row['end'] is None or row['end'] >= row['start'] for row in schedules)
    assert all(schedules[index]['end'] <= schedules[index+1]['start']
               for index in range(len(schedules) - 1))


def test_first_enable_of_initially_disabled_check(tmp_path):
    store = Store(tmp_path / 'test.db')
    store.initialize(now=100)
    check_id = store.create_check(CheckConfig(enabled=False), now=100)
    store.update_check(check_id, CheckConfig(), now=105)
    assert window(store, check_id, 99, 111, .95)['eligible_slots'] == 2
