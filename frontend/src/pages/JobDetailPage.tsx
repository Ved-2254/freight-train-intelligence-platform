import { useCallback, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { Alert, Card, ProgressBar, Stat, StatusBadge } from "../components/common";
import {
  ClassCountChart, Downloads, ResultNotes, SequenceStrip, VideoPlayer, WagonTable, wagonSeekTime,
  type VideoPlayerHandle,
} from "../components/results";
import { api, apiUrl, ApiError, newIdempotencyKey } from "../lib/api";
import { completenessLabel, elapsedSeconds, formatDateTime, formatDuration, stageLabel } from "../lib/format";
import { usePolling } from "../lib/usePolling";
import { FINAL_STATUSES, type Job, type JobResults, type WagonRecord } from "../lib/types";

const POLL_MS = 2000;

export function JobDetailPage() {
  const { jobId = "" } = useParams();
  const navigate = useNavigate();
  const [job, setJob] = useState<Job | null>(null);
  const [results, setResults] = useState<JobResults | null>(null);
  const [error, setError] = useState<ApiError | Error | null>(null);
  const [busy, setBusy] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const player = useRef<VideoPlayerHandle>(null);

  const finished = job ? FINAL_STATUSES.includes(job.status) : false;

  const refresh = useCallback(async () => {
    try {
      const j = await api.getJob(jobId);
      setJob(j);
      setError(null);
      if (j.status === "completed" && !results) {
        setResults(await api.getResults(jobId));
      }
    } catch (err) {
      setError(err instanceof Error ? err : new Error(String(err)));
    }
  }, [jobId, results]);

  // Poll until the job reaches a final state; a 404 stops polling too.
  const notFound = error instanceof ApiError && error.status === 404;
  usePolling(refresh, POLL_MS, !finished && !notFound);

  const cancel = async () => {
    if (!window.confirm("Cancel this job? Processing stops within about a second.")) return;
    setBusy(true);
    try {
      await api.cancelJob(jobId);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err : new Error(String(err)));
    } finally {
      setBusy(false);
    }
  };

  const retry = async () => {
    if (!job) return;
    setBusy(true);
    try {
      const created = await api.createJob(job.video_id, job.options, newIdempotencyKey());
      setResults(null);
      navigate(`/jobs/${created.job_id}`);
    } catch (err) {
      if (err instanceof ApiError && err.code === "JOB_ALREADY_ACTIVE" && typeof err.details.job_id === "string") {
        navigate(`/jobs/${err.details.job_id}`);
      } else {
        setError(err instanceof Error ? err : new Error(String(err)));
      }
    } finally {
      setBusy(false);
    }
  };

  const showWagon = (w: Pick<WagonRecord, "wagon_uid" | "crossing_time_s" | "first_seen_s" | "last_seen_s">) => {
    setSelected(w.wagon_uid);
    player.current?.seek(wagonSeekTime(w));
  };

  if (notFound) {
    return (
      <div className="stack">
        <Alert kind="error" title="Job not found">This job does not exist or was removed.</Alert>
        <div><Link to="/jobs">Back to jobs</Link></div>
      </div>
    );
  }
  if (!job) {
    return error ? <Alert kind="error" title="Could not load the job">{error.message}</Alert> : <p className="muted">Loading...</p>;
  }

  const r = results?.result;
  const wagonsByUid = new Map((r?.wagons ?? []).map((w) => [w.wagon_uid, w]));
  const summary = results?.summary ?? job.result_summary;
  const excluded = summary?.excluded_classes ?? [];
  const excludedCount = summary ? summary.total_rolling_stock - summary.total_wagons : 0;
  const runningFor = elapsedSeconds(job.started_at, job.finished_at);

  return (
    <div className="stack">
      <div className="page-header">
        <div className="row">
          <h1>{job.video_filename ?? "Video analysis"}</h1>
          <StatusBadge status={job.status} />
        </div>
        <p className="mono small">{job.job_id}</p>
      </div>

      {error && !notFound && <Alert kind="warning" title="Connection problem">{error.message}. Retrying.</Alert>}

      {(job.status === "queued" || job.status === "running") && (
        <Card title="Processing">
          <div className="stack" style={{ gap: 16 }}>
            <div className="row">
              <span>{stageLabel(job.stage)}</span>
              <div className="spacer" />
              <span className="muted">
                {job.progress_percent != null ? `${Math.round(job.progress_percent)}%` : ""}
              </span>
            </div>
            <ProgressBar value={job.status === "queued" ? 0 : job.progress_percent} />
            <div className="row">
              <span className="muted small">
                {job.message}
                {runningFor != null && ` | running for ${formatDuration(runningFor)}`}
                {job.attempts > 1 && ` | attempt ${job.attempts}`}
              </span>
              <div className="spacer" />
              <button className="btn btn-small btn-danger" disabled={busy || job.cancel_requested} onClick={cancel}>
                {job.cancel_requested ? "Cancelling..." : "Cancel"}
              </button>
            </div>
          </div>
        </Card>
      )}

      {(job.status === "failed" || job.status === "cancelled") && (
        <Alert kind={job.status === "failed" ? "error" : "info"} title={job.status === "failed" ? "Processing failed" : "Job cancelled"}>
          <div>{job.error?.message ?? "No results are available for this job."}</div>
          {job.error?.code && <div className="mono small" style={{ marginTop: 4 }}>{job.error.code}</div>}
          <div className="row" style={{ marginTop: 16 }}>
            <button className="btn btn-small" disabled={busy} onClick={retry}>Run again</button>
            <Link className="btn btn-small" to="/">Upload another video</Link>
          </div>
        </Alert>
      )}

      {job.status === "completed" && !results && <p className="muted">Loading results...</p>}

      {job.status === "completed" && r && summary && (
        <>
          <div className="stats">
            <Stat primary label={excluded.length ? `Wagons (excluding ${excluded.join(", ")})` : "Wagons"} value={summary.total_wagons} />
            {excluded.length > 0 && <Stat label={excluded.join(", ")} value={excludedCount} />}
            <Stat label="Total rolling stock" value={summary.total_rolling_stock} />
            <Stat label="Uncertain in sequence" value={summary.uncertain_sequence_items ?? 0} />
          </div>

          {summary.sequence_completeness && summary.sequence_completeness !== "complete" && (
            <Alert kind="warning" title={`Sequence: ${completenessLabel(summary.sequence_completeness)}`}>
              Part of the train may be outside the video, so the first or last wagons might be missing.
            </Alert>
          )}

          <Card title="Wagon sequence">
            <p className="muted small" style={{ marginTop: 0, marginBottom: 16 }}>
              In the order the wagons passed the reference line ({(r.sequence_info.travel_direction ?? "").replace(/_/g, " ")}).
              Select a wagon to jump to it in the video.
            </p>
            <SequenceStrip
              items={r.sequence}
              selected={selected}
              onSelect={(uid) => {
                const w = wagonsByUid.get(uid);
                if (w) showWagon(w);
              }}
            />
          </Card>

          <div className="stats" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))", gap: 32 }}>
            <Card title="Wagons by type">
              <ClassCountChart counts={summary.type_counts} excluded={excluded} />
            </Card>
            <Card title="Video details">
              <dl className="meta-grid" style={{ margin: 0 }}>
                <div><dt>Duration</dt><dd>{formatDuration(r.input?.duration_seconds)}</dd></div>
                <div><dt>Resolution</dt><dd>{r.input ? `${r.input.width} x ${r.input.height}` : "-"}</dd></div>
                <div><dt>Frames analysed</dt><dd>{r.sampling.sampled_frames ?? "-"} of {r.sampling.decoded_frames ?? "-"}</dd></div>
                <div><dt>Processing time</dt><dd>{formatDuration(r.timing_seconds.total)}</dd></div>
                <div><dt>Model</dt><dd>{r.model.model_file ?? "-"}</dd></div>
                <div><dt>Finished</dt><dd>{formatDateTime(job.finished_at)}</dd></div>
              </dl>
            </Card>
          </div>

          {job.links.annotated_video && (
            <Card title="Annotated video">
              {summary.browser_playable_video === false ? (
                <p className="muted">
                  This video uses a codec browsers cannot play.{" "}
                  <a href={`${apiUrl(job.links.annotated_video)}?download=true`}>Download it</a> to watch.
                </p>
              ) : (
                <VideoPlayer ref={player} src={apiUrl(job.links.annotated_video)} />
              )}
            </Card>
          )}

          <Card title="Wagon details">
            <WagonTable wagons={r.wagons} selected={selected} onSelect={showWagon} />
          </Card>

          <Card title="Notes">
            <ResultNotes result={r} />
            {!r.warnings.length && !r.unresolved_identities.length && !(r.sequence_info.notes ?? []).length && (
              <p className="muted">No warnings.</p>
            )}
          </Card>

          <Card title="Downloads">
            <Downloads links={job.links} />
          </Card>
        </>
      )}
    </div>
  );
}
