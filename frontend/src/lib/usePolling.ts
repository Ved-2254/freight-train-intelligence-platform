import { useEffect, useRef } from "react";

/**
 * Calls `fn` immediately and then every `intervalMs` while `enabled` is true.
 * The next call is scheduled only after the previous one finished, so slow responses never pile up.
 */
export function usePolling(fn: () => Promise<unknown> | void, intervalMs: number, enabled: boolean): void {
  const fnRef = useRef(fn);
  fnRef.current = fn;

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const tick = async () => {
      try {
        await fnRef.current();
      } finally {
        if (!cancelled) timer = setTimeout(tick, intervalMs);
      }
    };
    void tick();

    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [intervalMs, enabled]);
}
