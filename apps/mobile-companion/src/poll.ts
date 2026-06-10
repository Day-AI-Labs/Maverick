/* Simple polling hook: fetch now, then every `intervalMs`.
 *
 * Deliberately not SSE/websockets — plain polling is dependency-light,
 * battery-predictable, and matches the dashboard's own goal-events polling
 * model. The fetcher's failures are surfaced, not swallowed, so screens can
 * fall back to the offline cache. */
import { useCallback, useEffect, useRef, useState } from "react";

export type Polled<T> = {
  data: T | null;
  error: string | null;
  refresh: () => void;
};

export function usePolling<T>(
  fetcher: () => Promise<T>,
  intervalMs: number,
): Polled<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const alive = useRef(true);

  const tick = useCallback(() => {
    fetcher().then(
      (d) => {
        if (!alive.current) return;
        setData(d);
        setError(null);
      },
      (e: unknown) => {
        if (!alive.current) return;
        setError(e instanceof Error ? e.message : String(e));
      },
    );
  }, [fetcher]);

  useEffect(() => {
    alive.current = true;
    tick();
    const id = setInterval(tick, intervalMs);
    return () => {
      alive.current = false;
      clearInterval(id);
    };
  }, [tick, intervalMs]);

  return { data, error, refresh: tick };
}
