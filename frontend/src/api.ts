export class ApiError extends Error {
  constructor(message: string, public status?: number) { super(message); }
}

function errorDetail(value: unknown): string {
  if (typeof value === 'string') return value;
  if (Array.isArray(value)) return value.map(item => {
    const issue = item as { loc?: unknown[]; msg?: string };
    return `${issue.loc?.slice(1).join('.') || 'Request'}: ${issue.msg || 'Invalid value'}`;
  }).join('; ');
  return 'The backend could not complete this request.';
}

// One queue for polling AND mutations. A rejected/aborted request never poisons
// the queue. Request deadlines prevent one stalled connection blocking it forever.
export class SerialApi {
  private tail: Promise<unknown> = Promise.resolve();
  constructor(private fetcher: typeof fetch = (...args) => fetch(...args)) {}
  request<T>(path: string, init: RequestInit = {}, signal?: AbortSignal): Promise<T> {
    const operation = this.tail.then(async () => {
      if (signal?.aborted) throw new DOMException('Cancelled', 'AbortError');
      const controller = new AbortController();
      const abort = () => controller.abort();
      signal?.addEventListener('abort', abort, { once: true });
      const timer = setTimeout(abort, 10000);
      try {
        const response = await this.fetcher(path, { ...init, signal: controller.signal,
          headers: { 'Content-Type': 'application/json', ...init.headers } });
        let body: unknown;
        try { body = await response.json(); }
        catch { throw new ApiError('The backend returned an unreadable response.', response.status); }
        if (!response.ok) throw new ApiError(errorDetail((body as { detail?: unknown })?.detail), response.status);
        return body as T;
      } catch (error) {
        if (signal?.aborted) throw new DOMException('Cancelled', 'AbortError');
        if (error instanceof ApiError) throw error;
        if (controller.signal.aborted) throw new ApiError('Request timed out. Check that the backend is running.');
        throw new ApiError('Cannot connect to the backend. Check the startup terminal and retry.');
      } finally {
        clearTimeout(timer);
        signal?.removeEventListener('abort', abort);
      }
    });
    this.tail = operation.catch(() => undefined);
    return operation;
  }
}
export const api = new SerialApi();
