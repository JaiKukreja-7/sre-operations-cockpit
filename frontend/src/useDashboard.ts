import { useEffect, useState } from 'react';
import { api } from './api';
import type { Check, Demo, PolicyName, Result, Summary } from './types';

export type Snapshot = { summary: Summary; results: Result[]; demo: Demo | null; demoError: string | null };
export function useDashboard(checkId: number, policy: PolicyName, refreshKey: number) {
  const [checks, setChecks] = useState<Check[]>([]);
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    const controller = new AbortController();
    setSnapshot(null); setError(null); setLoading(true);
    async function poll() {
      const started = performance.now();
      setRefreshing(true);
      try {
        const list = await api.request<Check[]>('/api/checks', {}, controller.signal);
        if (!active) return;
        setChecks(list);
        if (!list.length) { setSnapshot(null); setError(null); return; }
        if (!list.some(check => check.id === checkId)) throw new Error('Selected check no longer exists. Select another check.');
        const summary = await api.request<Summary>(`/api/checks/${checkId}/summary?policy=${policy}`, {}, controller.signal);
        const results = await api.request<Result[]>(`/api/checks/${checkId}/results?limit=100`, {}, controller.signal);
        let demo: Demo | null = null;
        let demoError: string | null = null;
        try { demo = await api.request<Demo>('/api/demo', {}, controller.signal); }
        catch (error) { demoError = (error as Error).message; }
        if (active) { setSnapshot({ summary, results, demo, demoError }); setError(null); }
      } catch (error) {
        if (active) setError((error as Error).message);
      } finally {
        if (active) {
          setLoading(false); setRefreshing(false);
          timer = setTimeout(poll, Math.max(0, 5000 - (performance.now() - started)));
        }
      }
    }
    void poll();
    return () => { active = false; controller.abort(); clearTimeout(timer); };
  }, [checkId, policy, refreshKey]);
  return { checks, snapshot, error, loading, refreshing };
}
