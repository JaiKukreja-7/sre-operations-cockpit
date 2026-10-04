import { useEffect, useState } from 'react';
import type { Check, CheckConfig } from './types';
export function CheckForm({ check, busy, save }: { check: Check; busy: boolean; save: (config: CheckConfig) => Promise<void> }) {
  const { id: _id, ...config } = check;
  const [draft, setDraft] = useState(config);
  const [dirty, setDirty] = useState(false);
  const [validation, setValidation] = useState('');
  useEffect(() => { if (!dirty) { const { id: _id, ...value } = check; setDraft(value); } }, [check, dirty]);
  const update = <K extends keyof CheckConfig>(key: K, value: CheckConfig[K]) => { setDraft(current => ({ ...current, [key]: value })); setDirty(true); setValidation(''); };
  return <section className="panel"><p className="eyebrow">CHECK CONFIGURATION</p><h2>Assertions & schedule</h2>
    <p className="target">{check.url}</p>
    <form onSubmit={async event => {
      event.preventDefault();
      if (!(draft.timeout_seconds > 0) || !(draft.latency_threshold_ms > 0)) { setValidation('Timeout and latency threshold must be greater than zero.'); return; }
      if (!(draft.timeout_seconds < draft.interval_seconds)) { setValidation('Timeout must be less than interval.'); return; }
      try { await save(draft); setDirty(false); setValidation(''); } catch { /* parent renders server errors */ }
    }}>
      <fieldset disabled={busy} className="form-grid">
        <label className="wide">Check name<input required maxLength={100} value={draft.name} onChange={event => update('name', event.target.value)}/></label>
        <label>Interval (seconds)<input type="number" required min={1} max={3600} step={1} value={Number.isNaN(draft.interval_seconds) ? '' : draft.interval_seconds} onChange={event => update('interval_seconds', event.target.valueAsNumber)}/></label>
        <label>Timeout (seconds)<input type="number" required min={0} max={60} step="any" value={Number.isNaN(draft.timeout_seconds) ? '' : draft.timeout_seconds} onChange={event => update('timeout_seconds', event.target.valueAsNumber)}/></label>
        <label>Expected HTTP status<input type="number" required min={100} max={599} step={1} value={Number.isNaN(draft.expected_status) ? '' : draft.expected_status} onChange={event => update('expected_status', event.target.valueAsNumber)}/></label>
        <label>Latency threshold (ms)<input type="number" required min={0} max={60000} step="any" value={Number.isNaN(draft.latency_threshold_ms) ? '' : draft.latency_threshold_ms} onChange={event => update('latency_threshold_ms', event.target.valueAsNumber)}/></label>
        <label className="wide">Required text<input maxLength={1000} value={draft.required_text} onChange={event => update('required_text', event.target.value)}/><span className="hint">Leave empty to disable the text assertion.</span></label>
        <label className="checkbox wide"><input type="checkbox" checked={draft.enabled} onChange={event => update('enabled', event.target.checked)}/>Monitoring enabled</label>
        {validation && <p role="alert" className="form-error wide">{validation}</p>}
        <button className="primary wide" type="submit" disabled={!dirty || busy}>{busy ? 'Saving…' : 'Save configuration'}</button>
      </fieldset>
    </form>
  </section>;
}
