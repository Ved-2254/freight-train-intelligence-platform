import type { ReactNode } from "react";
import type { JobStatus } from "../lib/types";

const STATUS_LABELS: Record<JobStatus, string> = {
  queued: "Queued",
  running: "Running",
  completed: "Completed",
  failed: "Failed",
  cancelled: "Cancelled",
};

export function StatusBadge({ status }: { status: JobStatus }) {
  return <span className={`badge badge-${status}`}>{STATUS_LABELS[status]}</span>;
}

export function TrainIcon() {
  return (
    <svg
      className="train-locomotive"
      viewBox="0 0 42 24"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden="true"
    >
      {/* Front cowcatcher / pilot plow */}
      <polygon points="36,17 41,20.5 36,20.5" fill="var(--muted)" />

      {/* Main engine body */}
      <rect x="5" y="7" width="31" height="11" rx="2" fill="var(--accent)" />

      {/* Cab section with contrasting tone */}
      <path d="M5 7 L23 7 L23 18 L5 18 Z" fill="var(--accent-hover)" />

      {/* Cab windows */}
      <rect x="8" y="9" width="5.5" height="4.5" rx="1" fill="var(--surface)" />
      <rect x="15.5" y="9" width="5.5" height="4.5" rx="1" fill="var(--surface)" />

      {/* Rooftop horn and exhaust stack */}
      <rect x="26" y="4.5" width="4" height="2.5" rx="0.8" fill="var(--text)" />
      <rect x="11" y="5" width="7" height="2" rx="0.8" fill="var(--text)" />

      {/* Subtle steam puffs from stack */}
      <circle cx="28" cy="2" r="1.2" className="steam-puff steam-1" fill="var(--muted-light)" opacity="0.6" />
      <circle cx="25" cy="0.8" r="1" className="steam-puff steam-2" fill="var(--muted-light)" opacity="0.4" />

      {/* Front nose / headlight housing */}
      <path d="M36 10 L38.5 12 L38.5 18 L36 18 Z" fill="var(--accent)" />
      {/* Headlight lamp */}
      <circle cx="38" cy="13" r="1.6" fill="#fbbf24" />
      {/* Headlight beam glow */}
      <polygon points="39.6,13 42,11.5 42,14.5" fill="#fef08a" opacity="0.75" />

      {/* Body radiator / ventilation slits */}
      <line x1="26" y1="10.5" x2="26" y2="15" stroke="var(--accent-text)" strokeWidth="1" strokeLinecap="round" opacity="0.5" />
      <line x1="29" y1="10.5" x2="29" y2="15" stroke="var(--accent-text)" strokeWidth="1" strokeLinecap="round" opacity="0.5" />
      <line x1="32" y1="10.5" x2="32" y2="15" stroke="var(--accent-text)" strokeWidth="1" strokeLinecap="round" opacity="0.5" />

      {/* Underbody frame chassis */}
      <rect x="3" y="17.5" width="35" height="2" fill="var(--text)" rx="0.5" />

      {/* Bogey wheels rolling on top of the rail line */}
      <circle cx="9" cy="20.5" r="2.6" fill="var(--text)" stroke="var(--surface)" strokeWidth="0.8" />
      <circle cx="16" cy="20.5" r="2.6" fill="var(--text)" stroke="var(--surface)" strokeWidth="0.8" />
      <circle cx="24.5" cy="20.5" r="2.6" fill="var(--text)" stroke="var(--surface)" strokeWidth="0.8" />
      <circle cx="32" cy="20.5" r="2.6" fill="var(--text)" stroke="var(--surface)" strokeWidth="0.8" />

      {/* Rear coupler */}
      <rect x="1" y="15.5" width="2.5" height="2" rx="0.5" fill="var(--muted)" />
    </svg>
  );
}

export function ProgressBar({ value }: { value: number | null }) {
  if (value == null) {
    return (
      <div className="train-track-wrap indeterminate" role="progressbar" aria-label="In progress">
        <div className="train-track-sleepers" />
        <div className="train-track-rail" />
        <div className="train-track-progress indeterminate" />
        <div className="train-runner indeterminate">
          <TrainIcon />
        </div>
      </div>
    );
  }
  const v = Math.max(0, Math.min(100, value));
  return (
    <div
      className="train-track-wrap"
      role="progressbar"
      aria-valuenow={v}
      aria-valuemin={0}
      aria-valuemax={100}
    >
      <div className="train-track-sleepers" />
      <div className="train-track-rail" />
      <div className="train-track-progress" style={{ width: `${v}%` }} />
      <div
        className="train-runner"
        style={{ left: `calc(${v}% - ${(v / 100) * 42}px)` }}
      >
        <TrainIcon />
      </div>
    </div>
  );
}

export function Alert({ kind, title, children }: { kind: "error" | "warning" | "info"; title?: string; children?: ReactNode }) {
  return (
    <div className={`alert alert-${kind}`} role={kind === "error" ? "alert" : "status"}>
      {title && <strong>{title}</strong>}
      {children}
    </div>
  );
}

export function Stat({ label, value, primary }: { label: string; value: ReactNode; primary?: boolean }) {
  return (
    <div className={`stat${primary ? " stat-primary" : ""}`}>
      <div className="stat-value">{value}</div>
      <div className="stat-label">{label}</div>
    </div>
  );
}

export function Card({ title, actions, children }: { title?: string; actions?: ReactNode; children: ReactNode }) {
  return (
    <section className="card">
      {(title || actions) && (
        <div className="row" style={{ marginBottom: 24 }}>
          {title && <h2>{title}</h2>}
          <div className="spacer" />
          {actions}
        </div>
      )}
      {children}
    </section>
  );
}
