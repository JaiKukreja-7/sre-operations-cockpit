import { it, expect, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { CheckForm } from './CheckForm';
import type { Check } from './types';
const check: Check = { id: 1, name: 'Local demo', url: 'http://127.0.0.1:8001/probe', interval_seconds: 5, timeout_seconds: 2, expected_status: 200, required_text: 'synthetic demo OK', latency_threshold_ms: 500, enabled: true };
it('protects edits from polling and validates timeout < interval', () => {
  const save = vi.fn();
  const { rerender } = render(<CheckForm check={check} busy={false} save={save}/>);
  fireEvent.change(screen.getByLabelText('Timeout (seconds)'), { target: { value: '6' } });
  rerender(<CheckForm check={{ ...check }} busy={false} save={save}/>);
  expect(screen.getByLabelText('Timeout (seconds)')).toHaveValue(6);
  fireEvent.submit(screen.getByRole('button', { name: 'Save configuration' }).closest('form')!);
  expect(screen.getByRole('alert')).toHaveTextContent('Timeout must be less than interval');
  expect(save).not.toHaveBeenCalled();
});
it('rejects zero timeout consistently with the backend exclusive minimum', () => {
  const save = vi.fn();
  render(<CheckForm check={check} busy={false} save={save}/>);
  fireEvent.change(screen.getByLabelText('Timeout (seconds)'), { target: { value: '0' } });
  fireEvent.submit(screen.getByRole('button', { name: 'Save configuration' }).closest('form')!);
  expect(screen.getByRole('alert')).toHaveTextContent('must be greater than zero');
  expect(save).not.toHaveBeenCalled();
});
