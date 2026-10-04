export type CheckConfig = {
  name: string; url: string; interval_seconds: number; timeout_seconds: number;
  expected_status: number; required_text: string; latency_threshold_ms: number; enabled: boolean;
};
export type Check = CheckConfig & { id: number };
export type Demo = { mode: 'Healthy' | 'Slow' | 'Failing'; delay_seconds: number };
export type PolicyName = 'demo' | 'thirty_day';
export type WindowMetrics = {
  window_start: string; window_end: string; good: number; bad: number; unknown: number;
  pending: number; eligible_slots: number; observed_events: number; unrecorded_slots: number;
  recorded_unknown: number; inferred_unknown: number; awaiting_slots: number;
  sli: number | null; allowed_bad_events: number; remaining_budget: number;
  burn_rate: number | null; sample_coverage: number | null;
};
export type Summary = {
  check_id: number; policy_name: PolicyName; generated_at: string; slot_boundary: string;
  dispatch_grace_seconds: number;
  policy: { slo_target: number; window_seconds: number; short_window_seconds: number;
    long_window_seconds: number; short_min_samples: number; long_min_samples: number; alert_burn_threshold: number };
  summary: WindowMetrics;
  alert: { state: 'FIRING' | 'OK' | 'INSUFFICIENT_DATA'; short: WindowMetrics;
    long: WindowMetrics; minimum_samples_met: boolean };
};
export type Result = { id: number; check_id: number; schedule_id: number; scheduled_at: string;
  completed_at: string | null; http_status: number | null; latency_ms: number | null;
  outcome: 'GOOD' | 'BAD' | 'UNKNOWN'; failure_reason: string | null };
