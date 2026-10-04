import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { number, percentage, latencySegments } from './presentation';
import { LatencyChart } from './LatencyChart';
import type { Result } from './types';

describe('backend metric presentation', () => {
  it('preserves negative budgets and distinguishes zero from null', () => {
    expect(number(-1.5)).toMatch(/^-/);
    expect(number(-1.5)).not.toBe(number(1.5));
    expect(number(-0.001)).toMatch(/^-0[.,]001$/);
    expect(number(-0.000000001)).toBe('-1.00e-9');
    expect(percentage(0)).toBe('0%');
    expect(percentage(null)).toBe('No data');
    expect(number(null, '×')).toBe('No data');
  });
  it('never joins latency across unknown values or absent slots', () => {
    const rows = [0, 5, 10, 25].map((seconds, index) => ({ id: index, scheduled_at: new Date(seconds * 1000).toISOString(), latency_ms: index === 1 ? null : 20 }) as Result);
    expect(latencySegments(rows, row => row.id, value => value, 5)).toEqual(['M0,20', 'M2,20', 'M3,20']);
  });
  it('renders a truthful empty chart without fabricated points', () => {
    render(<LatencyChart results={[]} interval={5} threshold={500} end="2026-01-01T00:00:00Z"/>);
    expect(screen.getByText(/No data/)).toBeVisible();
    expect(screen.queryByTestId('latency-segment')).not.toBeInTheDocument();
  });
});
