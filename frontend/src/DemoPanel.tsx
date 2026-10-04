import { useEffect, useState } from 'react';
import type { Demo } from './types';
export function DemoPanel({ demo, error, busy, change }: { demo: Demo | null; error: string | null; busy: boolean; change: (control: Demo) => Promise<void> }) {
  const [delay, setDelay] = useState('1');
  const [dirty, setDirty] = useState(false);
  const [validation, setValidation] = useState('');
  useEffect(() => { if (demo && !dirty) setDelay(String(demo.delay_seconds)); }, [demo, dirty]);
  return <section className="panel"><p className="eyebrow">LOCAL DEMO SERVICE</p><h2>Test recovery</h2>
    <p>Current mode: <strong data-testid="demo-mode">{demo?.mode || 'No data'}</strong></p>
    {error && <p role="alert" className="form-error">{error}</p>}
    <label>Slow delay (seconds)<input type="number" min={0} max={30} step="any" value={delay} onChange={event => { setDelay(event.target.value); setDirty(true); setValidation(''); }}/></label>
    <div className="mode-buttons">{(['Healthy', 'Slow', 'Failing'] as const).map(mode => <button key={mode} disabled={busy || !demo} aria-pressed={demo?.mode === mode} onClick={async () => {
      const value = Number(delay);
      if (!delay.trim() || !Number.isFinite(value) || value < 0 || value > 30) { setValidation('Delay must be between 0 and 30 seconds.'); return; }
      try { await change({ mode, delay_seconds: value }); setDirty(false); } catch { /* parent renders backend errors */ }
    }}>{mode}</button>)}</div>
    {validation && <p className="form-error" role="alert">{validation}</p>}
    <p className="muted">Slow returns HTTP 200 after the delay. Failing returns HTTP 500. The worker evaluates the configured assertions.</p>
  </section>;
}
