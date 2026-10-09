export function formatBytes(bytes: number | null | undefined): string {
  if (bytes == null) return "-";
  const units = ["B", "KB", "MB", "GB"];
  let value = bytes;
  let i = 0;
  while (value >= 1024 && i < units.length - 1) {
    value /= 1024;
    i++;
  }
  return `${value.toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
}

export function formatDuration(seconds: number | null | undefined): string {
  if (seconds == null || !isFinite(seconds)) return "-";
  const s = Math.max(0, Math.round(seconds));
  const m = Math.floor(s / 60);
  return m > 0 ? `${m} min ${s % 60} s` : `${s} s`;
}

export function formatSeconds(seconds: number | null | undefined, digits = 1): string {
  return seconds == null ? "-" : `${seconds.toFixed(digits)} s`;
}

/** Local date/time for an ISO UTC timestamp from the API. */
export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "-";
  const d = new Date(iso);
  return isNaN(d.getTime()) ? iso : d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

export function elapsedSeconds(fromIso: string | null, toIso?: string | null): number | null {
  if (!fromIso) return null;
  const start = new Date(fromIso).getTime();
  const end = toIso ? new Date(toIso).getTime() : Date.now();
  return (end - start) / 1000;
}

export function percent(value: number | null | undefined, digits = 0): string {
  return value == null ? "-" : `${(value * 100).toFixed(digits)}%`;
}

const STAGE_LABELS: Record<string, string> = {
  queued: "Waiting in queue",
  starting: "Starting",
  loading_model: "Loading model",
  validating: "Validating video",
  detecting_and_tracking: "Detecting and tracking",
  resolving: "Counting and sequencing",
  rendering: "Rendering annotated video",
  completed: "Completed",
  failed: "Failed",
  cancelled: "Cancelled",
};

export function stageLabel(stage: string | null): string {
  return stage ? (STAGE_LABELS[stage] ?? stage) : "-";
}

const COMPLETENESS_LABELS: Record<string, string> = {
  complete: "Complete",
  partial_start: "Partial (train already in view at start)",
  partial_end: "Partial (train still in view at end)",
  partial_both: "Partial (start and end)",
  empty: "No wagons",
};

export function completenessLabel(value: string | null | undefined): string {
  return value ? (COMPLETENESS_LABELS[value] ?? value) : "-";
}

/** "sequence_extrapolated" -> "sequence extrapolated" */
export function humanize(flag: string): string {
  return flag.replace(/_/g, " ");
}
