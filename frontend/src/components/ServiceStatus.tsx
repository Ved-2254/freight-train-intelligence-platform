import { useState } from "react";
import { api } from "../lib/api";
import { usePolling } from "../lib/usePolling";
import type { ReadyStatus } from "../lib/types";

type State = { kind: "checking" } | { kind: "down" } | { kind: "up"; ready: ReadyStatus };

/** Backend health indicator in the header, refreshed every 10 seconds. */
export function ServiceStatus() {
  const [state, setState] = useState<State>({ kind: "checking" });

  usePolling(async () => {
    try {
      setState({ kind: "up", ready: await api.ready() });
    } catch {
      setState({ kind: "down" });
    }
  }, 10_000, true);

  let label = "Checking backend";
  let color = "var(--muted)";
  let title = "";
  if (state.kind === "down") {
    label = "Backend offline";
    color = "var(--danger)";
    title = "The API is not reachable. Start it with the demo launcher.";
  } else if (state.kind === "up") {
    const { ready } = state;
    const failed = Object.entries(ready.checks).filter(([, c]) => !c.ok).map(([name]) => name);
    if (ready.status !== "ready") {
      label = "Backend not ready";
      color = "var(--danger)";
      title = failed.length ? `Failing checks: ${failed.join(", ")}` : "";
    } else if (!ready.worker.alive) {
      label = "Worker offline";
      color = "var(--warning)";
      title = "Jobs will wait in the queue until a worker is running.";
    } else {
      label = ready.worker.busy ? "Ready (processing)" : "Ready";
      color = "var(--success)";
    }
  }

  return (
    <span className="status-dot" style={{ ["--dot" as string]: color }} title={title} aria-live="polite">
      {label}
    </span>
  );
}
