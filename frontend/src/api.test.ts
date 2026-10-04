import { describe, it, expect, vi } from 'vitest';
import { SerialApi } from './api';

describe('serial API requests', () => {
  it('queues refresh and mutation requests without overlap, including failures', async () => {
    let release: () => void = () => {};
    let active = 0;
    let maxActive = 0;
    const calls: string[] = [];
    const fetcher = vi.fn(async (path: RequestInfo | URL) => {
      active++; maxActive = Math.max(maxActive, active); calls.push(String(path));
      if (calls.length === 1) await new Promise<void>(resolve => { release = resolve; });
      active--;
      return new Response(JSON.stringify(calls.length === 1 ? { detail: 'Unavailable' } : { ok: true }), { status: calls.length === 1 ? 503 : 200 });
    });
    const api = new SerialApi(fetcher);
    const first = api.request('/refresh').catch(error => error.message);
    const second = api.request('/mutation', { method: 'PUT' });
    await Promise.resolve();
    expect(calls).toEqual(['/refresh']);
    release();
    expect(await first).toBe('Unavailable');
    expect(await second).toEqual({ ok: true });
    expect(maxActive).toBe(1);
  });
  it('does not dispatch obsolete requests cancelled while queued', async () => {
    const fetcher = vi.fn(async () => new Response('{}'));
    const controller = new AbortController();
    const api = new SerialApi(fetcher);
    const promise = api.request('/obsolete', {}, controller.signal);
    controller.abort();
    await expect(promise).rejects.toMatchObject({ name: 'AbortError' });
    expect(fetcher).not.toHaveBeenCalled();
    await expect(api.request('/current')).resolves.toEqual({});
  });
  it('renders actual FastAPI field validation details', async () => {
    const api = new SerialApi(vi.fn(async () => new Response(JSON.stringify({ detail: [{ loc: ['body', 'timeout_seconds'], msg: 'Value must be positive' }] }), { status: 422 })));
    await expect(api.request('/config')).rejects.toMatchObject({ status: 422, message: 'timeout_seconds: Value must be positive' });
  });
  it('bounds a stalled request and continues the queue', async () => {
    vi.useFakeTimers();
    const api = new SerialApi(vi.fn((_path: RequestInfo | URL, init?: RequestInit) => new Promise<Response>((_resolve, reject) => {
      init?.signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')));
    })));
    const pending = api.request('/stalled').catch(error => error.message);
    await vi.advanceTimersByTimeAsync(10000);
    expect(await pending).toContain('timed out');
    vi.useRealTimers();
  });
});
