import type { Result } from './types';
import { date, latencySegments, number } from './presentation';
export function LatencyChart({ results, interval, threshold, end }: { results: Result[]; interval: number; threshold: number; end: string }) {
  const rows = [...results].sort((a, b) => Date.parse(a.scheduled_at) - Date.parse(b.scheduled_at));
  const start = rows.length ? Date.parse(rows[0].scheduled_at) : Date.parse(end);
  const stop = Math.max(Date.parse(end), start + 1000);
  const max = Math.max(threshold, 1, ...rows.map(row => row.latency_ms ?? 0)) * 1.2;
  const x = (row: Result) => 60 + (Date.parse(row.scheduled_at) - start) / (stop - start) * 820;
  const y = (value: number) => 190 - value / max * 150;
  const segments = latencySegments(rows, x, y, interval);
  return <section className="panel chart-panel" aria-labelledby="latency-title">
    <div className="section-heading"><div><p className="eyebrow">REQUEST PERFORMANCE</p><h2 id="latency-title">Latency over time</h2></div><span className="muted">Latest {results.length} results</span></div>
    <p className="muted">Missing latencies and scheduled gaps are never connected. Scroll the chart on small screens. Dashed line: current threshold.</p>
    {!rows.length ? <div className="empty">No data. Latency will appear after the worker completes a check.</div> : <>
      <div className="chart-scroll"><svg className="latency-chart" viewBox="0 0 920 240" role="img" aria-label="Latency chart in milliseconds. Missing values are gaps.">
        {[0, .5, 1].map(fraction => <g key={fraction}><line x1="60" x2="880" y1={y(max * fraction)} y2={y(max * fraction)} className="grid-line"/><text x="50" y={y(max * fraction) + 4} textAnchor="end">{number(max * fraction)}</text></g>)}
        <text x="10" y="22">ms</text>
        <line x1="60" x2="880" y1={y(threshold)} y2={y(threshold)} className="threshold"/>
        {segments.map((path, index) => <path key={index} d={path} className="latency-line" data-testid="latency-segment"/>)}
        {rows.filter(row => row.latency_ms !== null).map(row => <circle key={row.id} cx={x(row)} cy={y(row.latency_ms!)} r="3.5" className={`point ${row.outcome.toLowerCase()}`}><title>{date(row.scheduled_at)} UTC: {number(row.latency_ms, ' ms')} · {row.outcome}</title></circle>)}
        <text x="60" y="222">{date(rows[0].scheduled_at)} UTC</text><text x="880" y="222" textAnchor="end">{date(end)} UTC</text>
      </svg></div>
      {!segments.length && <p className="empty">No data. These results have no recorded latency.</p>}
    </>}
  </section>;
}
