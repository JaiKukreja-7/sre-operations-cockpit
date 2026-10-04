import type { Result } from './types';
// Display precision only; preserve small nonzero budgets instead of showing -0.
export const number = (value: number | null, suffix = '') => {
  if (value === null) return 'No data';
  const magnitude = Math.abs(value);
  const text = magnitude > 0 && magnitude < 0.000001 ? value.toExponential(2)
    : value.toLocaleString(undefined, magnitude > 0 && magnitude < 0.01
      ? { maximumSignificantDigits: 3 } : { maximumFractionDigits: 2 });
  return `${text}${suffix}`;
};
export const percentage = (value: number | null) => value === null ? 'No data' : number(value * 100, '%');
export const date = (value: string | null) => value === null ? 'No data' : new Date(value).toLocaleString(undefined, { timeZone: 'UTC', dateStyle: 'medium', timeStyle: 'medium' });
export function duration(seconds: number): string {
  if (seconds % 86400 === 0) return `${seconds / 86400} days`;
  if (seconds % 60 === 0) return `${seconds / 60} minutes`;
  return `${seconds} seconds`;
}
// Geometry only: metrics and outcomes always come from the backend.
export function latencySegments(rows: Result[], x: (row: Result) => number, y: (value: number) => number, interval: number) {
  const segments: string[] = [];
  let current = '';
  let previous: Result | undefined;
  for (const row of rows) {
    const gap = previous && Date.parse(row.scheduled_at) - Date.parse(previous.scheduled_at) > interval * 1500;
    if (row.latency_ms === null || gap) { if (current) segments.push(current); current = ''; }
    if (row.latency_ms !== null) current += `${current ? ' L' : 'M'}${x(row)},${y(row.latency_ms)}`;
    previous = row;
  }
  if (current) segments.push(current);
  return segments;
}
