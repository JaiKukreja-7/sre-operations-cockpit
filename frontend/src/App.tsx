import { useState } from 'react';
import { api } from './api';
import { CheckForm } from './CheckForm';
import { DemoPanel } from './DemoPanel';
import { LatencyChart } from './LatencyChart';
import { date, duration, number, percentage } from './presentation';
import type { CheckConfig, Demo, PolicyName } from './types';
import { useDashboard } from './useDashboard';

export function App() {
  const [checkId, setCheckId] = useState(1);
  const [policy, setPolicy] = useState<PolicyName>('demo');
  const [refreshKey, setRefreshKey] = useState(0);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [notice, setNotice] = useState('');
  const { checks, snapshot, error, loading, refreshing } = useDashboard(checkId, policy, refreshKey);
  const check = checks.find(check => check.id === checkId);
  async function mutate(path: string, body: CheckConfig | Demo, message: string) {
    setBusy(true); setActionError(null); setNotice('');
    try {
      await api.request(path, { method: 'PUT', body: JSON.stringify(body) });
      setNotice(message); setRefreshKey(value => value + 1);
    } catch (error) { setActionError((error as Error).message); throw error; }
    finally { setBusy(false); }
  }
  const metrics = snapshot?.summary.summary;
  const alert = snapshot?.summary.alert;
  return <main>
    <header className="masthead"><div><p className="eyebrow">SYNTHETIC MONITORING / LOCAL OPERATIONS</p><h1>SRE Operations Cockpit</h1><p>Know what passed. See what’s missing. Track the budget.</p></div><a className="docs-link" href="/docs">API documentation</a></header>
    <section className="toolbar" aria-label="Dashboard controls">
      <label>Monitoring check<select value={checkId} disabled={busy || !checks.length} onChange={event => { setCheckId(Number(event.target.value)); setNotice(''); setActionError(null); }}>{checks.map(check => <option key={check.id} value={check.id}>{check.name} · #{check.id}</option>)}</select></label>
      <label>Reliability policy<select value={policy} disabled={busy} onChange={event => setPolicy(event.target.value as PolicyName)}><option value="demo">Demo · short classroom policy</option><option value="thirty_day">Thirty-day reporting policy</option></select></label>
      <div className="refresh-status"><span className={`status-dot ${error ? 'disconnected' : ''}`}/>{loading ? 'Loading…' : refreshing ? 'Refreshing…' : 'Refreshes every 5 seconds'}<button disabled={busy || refreshing} onClick={() => setRefreshKey(value => value + 1)}>Refresh now</button></div>
    </section>
    {(error || actionError) && <div className="banner error" role="alert"><strong>{actionError ? 'Action failed' : 'Connection error'}</strong><p>{actionError || error}</p>{snapshot && <p>Showing the last successful response. Values may be stale.</p>}<button disabled={busy} onClick={() => { setActionError(null); setRefreshKey(value => value + 1); }}>Retry connection</button></div>}
    {notice && <p className="banner success" role="status">{notice}</p>}
    {loading && <div className="banner" role="status">Loading real monitoring data…</div>}
    {!loading && !error && !checks.length && <div className="empty panel">No checks configured. Create a local check through the API documentation.</div>}
    <section className="window-panel"><div><p className="eyebrow">REPORTING WINDOW</p><h2>{policy === 'demo' ? 'Demo policy' : 'Thirty-day reporting'}{snapshot ? ` · ${duration(snapshot.summary.policy.window_seconds)}` : ''}</h2><p>{snapshot ? `${date(metrics!.window_start)} → ${date(metrics!.window_end)} UTC` : 'No data'}</p></div><div><strong>SLO target: {snapshot ? percentage(snapshot.summary.policy.slo_target) : 'No data'}</strong><p className="muted">{policy === 'demo' ? 'Short demo window; separate from the thirty-day SLO report.' : 'Eligibility starts when checks are enabled; this may be partial thirty-day history.'}</p></div></section>
    <section className="metrics-grid" aria-label="Reliability metrics">
      <Metric title="SLI" value={percentage(metrics?.sli ?? null)} detail="GOOD / observed events"/>
      <Metric title="Monitoring coverage" value={percentage(metrics?.sample_coverage ?? null)} detail={metrics ? `${metrics.observed_events} observed / ${metrics.eligible_slots} eligible slots` : 'Includes missing scheduled slots'}/>
      <Metric title="Error budget remaining" value={number(metrics?.remaining_budget ?? null)} negative={(metrics?.remaining_budget ?? 0) < 0} detail={metrics ? `${number(metrics.allowed_bad_events)} allowed bad events · ${metrics.bad} bad` : 'Budget measured in events'}/>
      <Metric title="Burn rate" value={number(metrics?.burn_rate ?? null, '×')} detail="Calculated by the monitoring backend"/>
    </section>
    <div className="counts"><Count label="GOOD" value={metrics?.good} style="good"/><Count label="BAD" value={metrics?.bad} style="bad"/><Count label="UNKNOWN" value={metrics?.unknown} style="unknown"/><span>{metrics ? `${metrics.pending} pending · ${metrics.awaiting_slots} awaiting dispatch · ${metrics.inferred_unknown} UNKNOWN not yet recorded` : 'No data'}</span></div>
    <section className={`panel alert-panel ${alert?.state === 'FIRING' ? 'firing' : ''}`}><div><p className="eyebrow">MULTI-WINDOW BURN ALERT</p><h2 data-testid="alert-state">{alert?.state === 'INSUFFICIENT_DATA' ? 'Insufficient data' : alert?.state === 'FIRING' ? 'Firing' : alert?.state === 'OK' ? 'OK' : 'No data'}</h2><p className="muted">Both windows must meet their minimum observed samples and burn threshold. Coverage is reported separately.</p></div>{snapshot && <div className="alert-windows">{(['short', 'long'] as const).map(name => <div key={name}><strong>{duration(snapshot.summary.policy[`${name}_window_seconds`])} window</strong><p>{number(alert![name].burn_rate, '×')} burn · {alert![name].observed_events} / {snapshot.summary.policy[`${name}_min_samples`]} minimum samples</p></div>)}<p>Burn threshold: {number(snapshot.summary.policy.alert_burn_threshold, '×')}</p></div>}</section>
    <div className="work-grid"><div className="main-column">
      <LatencyChart results={snapshot?.results || []} interval={check?.interval_seconds || 5} threshold={check?.latency_threshold_ms || 500} end={snapshot?.summary.generated_at || new Date().toISOString()}/>
      <section className="panel results-panel"><div className="section-heading"><div><p className="eyebrow">PROBE HISTORY</p><h2>Recent results</h2></div><span className="muted">All times UTC</span></div>
        {!snapshot?.results.length ? <div className="empty">No data. Start or resume the monitoring worker to collect results.</div> : <div className="table-scroll"><table><thead><tr><th>Outcome</th><th>Scheduled</th><th>Completed</th><th>HTTP</th><th>Latency</th><th>Failure reason</th></tr></thead><tbody>{snapshot.results.map(row => <tr key={row.id} data-testid="result-row" data-scheduled-at={row.scheduled_at}><td><span className={`badge ${row.outcome.toLowerCase()}`}>{row.outcome}</span></td><td><time dateTime={row.scheduled_at}>{date(row.scheduled_at)}</time></td><td>{date(row.completed_at)}</td><td>{row.http_status ?? 'No data'}</td><td>{number(row.latency_ms, ' ms')}</td><td>{row.failure_reason || (row.outcome === 'GOOD' ? 'All assertions passed' : 'No failure reason recorded')}</td></tr>)}</tbody></table></div>}
      </section>
    </div><aside>{check && <CheckForm key={check.id} check={check} busy={busy} save={config => mutate(`/api/checks/${checkId}`, config, 'Configuration saved. Schedule history is preserved.')}/>}
      <DemoPanel demo={snapshot?.demo || null} error={snapshot?.demoError || null} busy={busy} change={control => mutate('/api/demo', control, `Demo changed to ${control.mode}. Waiting for the next scheduled result.`)}/>
    </aside></div>
    <footer>Data source: local FastAPI backend · {snapshot ? `Last successful snapshot: ${date(snapshot.summary.generated_at)} UTC` : 'No successful snapshot yet'} · Separate worker and demo processes</footer>
  </main>;
}
function Metric({ title, value, detail, negative = false }: { title: string; value: string; detail: string; negative?: boolean }) { return <article className={`metric ${negative ? 'over-budget' : ''}`} aria-label={title}><h2>{title}</h2><strong className="metric-value">{value}</strong><p>{detail}</p></article>; }
function Count({ label, value, style }: { label: string; value?: number; style: string }) { return <div className={`count ${style}`}><span>{label}</span><strong>{value ?? 'No data'}</strong></div>; }
