import { forwardRef, useImperativeHandle, useMemo, useRef, useState } from "react";
import { apiUrl } from "../lib/api";
import { classAbbreviation, classColor } from "../lib/classColors";
import { formatSeconds, humanize, percent } from "../lib/format";
import type { JobLinks, PipelineResult, SequenceItem, WagonRecord } from "../lib/types";

// Flags that indicate the record needs a human look (mirrors the backend's uncertainty flags).
const WARN_FLAGS = new Set([
  "class_uncertain", "ambiguous_identity", "duplicate_candidate", "possible_id_switch",
  "sequence_extrapolated", "direction_inconsistent", "stationary_object", "insufficient_evidence",
]);

/** Time in the annotated video at which a wagon is best seen. */
export function wagonSeekTime(w: Pick<WagonRecord, "crossing_time_s" | "first_seen_s" | "last_seen_s">): number {
  if (w.crossing_time_s != null) return Math.max(0, w.crossing_time_s);
  return Math.max(0, (w.first_seen_s + w.last_seen_s) / 2);
}

// ------------------------------------------------------------------ class counts

export function ClassCountChart({ counts, excluded }: { counts: Record<string, number>; excluded: string[] }) {
  const entries = Object.entries(counts).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
  const max = Math.max(1, ...entries.map(([, n]) => n));
  if (entries.length === 0) return <p className="muted">No wagons were counted.</p>;
  return (
    <div>
      {entries.map(([name, n]) => (
        <div className="bar-row" key={name}>
          <span className="bar-label" title={excluded.includes(name) ? "Not included in the wagon total" : undefined}>
            {name}{excluded.includes(name) ? " *" : ""}
          </span>
          <div className="bar-track">
            <div className="bar-fill" style={{ width: `${(100 * n) / max}%`, background: classColor(name) }} />
          </div>
          <span className="bar-count">{n}</span>
        </div>
      ))}
      {excluded.some((c) => c in counts) && (
        <p className="muted small" style={{ marginTop: 16 }}>* Shown in the sequence but not counted as wagons.</p>
      )}
    </div>
  );
}

// ------------------------------------------------------------------ sequence strip

export function SequenceStrip({
  items, selected, onSelect,
}: { items: SequenceItem[]; selected: string | null; onSelect: (uid: string) => void }) {
  const classes = useMemo(() => [...new Set(items.map((i) => i.class_name))], [items]);
  if (items.length === 0) return <p className="muted">No wagons in the sequence.</p>;
  return (
    <div className="sequence-container">
      <div className="sequence" role="list" aria-label="Wagon sequence">
        {items.map((item, idx) => (
          <div key={item.wagon_uid} className="wagon-block-wrap">
            <button
              role="listitem"
              className={`wagon-chip${item.uncertain ? " uncertain" : ""}${selected === item.wagon_uid ? " selected" : ""}`}
              style={{ ["--chip" as string]: classColor(item.class_name) }}
              title={`#${item.position} ${item.wagon_uid}: ${item.class_name}${item.uncertain ? " (uncertain)" : ""}`}
              onClick={() => onSelect(item.wagon_uid)}
            >
              <span className="pos">#{item.position}</span>
              <span className="class-code">{classAbbreviation(item.class_name)}</span>
            </button>
            {idx < items.length - 1 && <span className="coupler-link" aria-hidden="true" />}
          </div>
        ))}
      </div>
      {/* Subtle railway track baseline underneath the wagon sequence */}
      <div className="sequence-track-baseline" aria-hidden="true" />
      <div className="legend">
        {classes.map((c) => (
          <span className="legend-item" key={c}>
            <span className="swatch" style={{ background: classColor(c) }} />
            {c}
          </span>
        ))}
        <span className="legend-item">
          <span className="swatch swatch-uncertain" />
          Dashed border: uncertain
        </span>
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ video

export interface VideoPlayerHandle {
  seek: (seconds: number) => void;
}

export const VideoPlayer = forwardRef<VideoPlayerHandle, { src: string }>(function VideoPlayer({ src }, ref) {
  const video = useRef<HTMLVideoElement>(null);
  const [failed, setFailed] = useState(false);

  useImperativeHandle(ref, () => ({
    seek: (seconds: number) => {
      const v = video.current;
      if (!v) return;
      // Pause on the wagon's frame so it can be inspected; the user presses play if they want.
      v.pause();
      v.currentTime = Math.min(seconds, isFinite(v.duration) ? Math.max(0, v.duration - 0.05) : seconds);
      v.scrollIntoView({ behavior: "smooth", block: "center" });
    },
  }));

  if (failed) {
    return (
      <p className="muted">
        The browser could not play this video. <a href={`${src}?download=true`}>Download it</a> instead.
      </p>
    );
  }
  return (
    <div className="video-wrap">
      <video ref={video} src={src} controls preload="metadata" onError={() => setFailed(true)} />
    </div>
  );
});

// ------------------------------------------------------------------ wagon table

export function WagonTable({
  wagons, selected, onSelect,
}: { wagons: WagonRecord[]; selected: string | null; onSelect: (w: WagonRecord) => void }) {
  const [showAll, setShowAll] = useState(false);
  const counted = wagons.filter((w) => w.count_status === "counted");
  const rows = showAll ? wagons : counted;
  const hidden = wagons.length - counted.length;

  return (
    <div className="stack" style={{ gap: 16 }}>
      {hidden > 0 && (
        <label className="check">
          <input type="checkbox" checked={showAll} onChange={(e) => setShowAll(e.target.checked)} />
          Show {hidden} record{hidden === 1 ? "" : "s"} that were not counted
        </label>
      )}
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>#</th>
              <th>Wagon</th>
              <th>Class</th>
              <th>Confidence</th>
              <th>Seen</th>
              <th>Status and flags</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((w) => (
              <tr
                key={w.wagon_uid}
                className={`clickable${selected === w.wagon_uid ? " selected" : ""}`}
                onClick={() => onSelect(w)}
                title="Show this wagon in the video"
              >
                <td className="num">{w.sequence_position ?? "-"}</td>
                <td className="mono">{w.wagon_uid}</td>
                <td>
                  <span className="swatch" style={{ background: classColor(w.class_name), marginRight: 8 }} />
                  {w.class_name}
                  {w.class_name === "Unresolved" && w.class_best_guess && (
                    <span className="muted small"> (likely {w.class_best_guess})</span>
                  )}
                </td>
                <td className="num">{percent(w.class_confidence)}</td>
                <td className="num muted">{formatSeconds(w.first_seen_s)} to {formatSeconds(w.last_seen_s)}</td>
                <td>
                  {w.count_status !== "counted" && <span className="flag flag-warn">{humanize(w.count_status)}</span>}
                  {w.flags.map((f) => (
                    <span key={f} className={`flag${WARN_FLAGS.has(f) ? " flag-warn" : ""}`}>{humanize(f)}</span>
                  ))}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ notes

export function ResultNotes({ result }: { result: PipelineResult }) {
  const notes = result.sequence_info.notes ?? [];
  const { warnings, unresolved_identities: unresolved } = result;
  if (!warnings.length && !notes.length && !unresolved.length) return null;
  return (
    <div className="stack" style={{ gap: 20 }}>
      {warnings.length > 0 && (
        <div className="notes-group">
          <h3 className="notes-heading">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--warning)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
              <line x1="12" y1="9" x2="12" y2="13" />
              <line x1="12" y1="17" x2="12.01" y2="17" />
            </svg>
            Warnings
          </h3>
          <ul className="notes-list">
            {warnings.map((w, i) => <li key={i}>{w}</li>)}
          </ul>
        </div>
      )}
      {unresolved.length > 0 && (
        <div className="notes-group">
          <h3 className="notes-heading">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--info)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <circle cx="12" cy="12" r="10" />
              <line x1="12" y1="16" x2="12" y2="12" />
              <line x1="12" y1="8" x2="12.01" y2="8" />
            </svg>
            Identities that need review
          </h3>
          <ul className="notes-list">
            {unresolved.map((u, i) => (
              <li key={i}>
                <span className="mono">{u.wagon_uids.join(", ")}</span>: {u.detail}
              </li>
            ))}
          </ul>
        </div>
      )}
      {notes.length > 0 && (
        <div className="notes-group">
          <h3 className="notes-heading">How the sequence is ordered</h3>
          <ul className="notes-list muted">
            {notes.map((n, i) => <li key={i}>{n}</li>)}
          </ul>
        </div>
      )}
    </div>
  );
}

// ------------------------------------------------------------------ downloads

export function Downloads({ links }: { links: JobLinks }) {
  if (!links.exports) return null;
  return (
    <div className="downloads-row">
      <a className="btn" href={apiUrl(links.exports.csv)}>
        <svg className="btn-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
          <polyline points="7 10 12 15 17 10" />
          <line x1="12" y1="15" x2="12" y2="3" />
        </svg>
        Wagon table (CSV)
      </a>
      <a className="btn" href={apiUrl(links.exports.json)}>
        <svg className="btn-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
          <polyline points="7 10 12 15 17 10" />
          <line x1="12" y1="15" x2="12" y2="3" />
        </svg>
        Full results (JSON)
      </a>
      <a className="btn" href={apiUrl(links.exports.tracks_csv)}>
        <svg className="btn-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
          <polyline points="7 10 12 15 17 10" />
          <line x1="12" y1="15" x2="12" y2="3" />
        </svg>
        Frame observations (CSV)
      </a>
      {links.annotated_video && (
        <a className="btn" href={`${apiUrl(links.annotated_video)}?download=true`}>
          <svg className="btn-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
            <polyline points="7 10 12 15 17 10" />
            <line x1="12" y1="15" x2="12" y2="3" />
          </svg>
          Annotated video (MP4)
        </a>
      )}
    </div>
  );
}
