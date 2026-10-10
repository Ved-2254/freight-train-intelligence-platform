import { useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Alert, Card, ProgressBar } from "../components/common";
import { JobOptionsForm } from "../components/JobOptionsForm";
import { UploadDropzone, validateFile } from "../components/UploadDropzone";
import { RailSchematic } from "../components/RailSchematic";
import { UploadCapabilities } from "../components/UploadCapabilities";
import { api, ApiError, newIdempotencyKey } from "../lib/api";
import { formatBytes, formatDuration } from "../lib/format";
import type { JobOptions, Video } from "../lib/types";
import { uploadVideo, type UploadHandle, type UploadProgress } from "../lib/upload";

type Phase =
  | { kind: "idle" }
  | { kind: "uploading"; file: File; progress: UploadProgress }
  | { kind: "uploaded"; video: Video };

export function UploadPage() {
  const navigate = useNavigate();
  const [phase, setPhase] = useState<Phase>({ kind: "idle" });
  const [error, setError] = useState<string | null>(null);
  const [options, setOptions] = useState<JobOptions>({});
  const [starting, setStarting] = useState(false);
  const handle = useRef<UploadHandle | null>(null);
  // One key per uploaded video: repeated clicks on "Analyse" cannot start duplicate jobs.
  const idempotencyKey = useRef(newIdempotencyKey());

  const onFile = async (file: File) => {
    setError(null);
    const problem = validateFile(file);
    if (problem) {
      setError(problem);
      return;
    }
    setPhase({ kind: "uploading", file, progress: { loaded: 0, total: file.size } });
    const h = uploadVideo(file, (progress) => setPhase({ kind: "uploading", file, progress }));
    handle.current = h;
    try {
      const video = await h.promise;
      idempotencyKey.current = newIdempotencyKey();
      setPhase({ kind: "uploaded", video });
    } catch (err) {
      setPhase({ kind: "idle" });
      if (!(err instanceof ApiError && err.code === "UPLOAD_ABORTED")) {
        setError(err instanceof Error ? err.message : "Upload failed");
      }
    } finally {
      handle.current = null;
    }
  };

  const startAnalysis = async (video: Video) => {
    setStarting(true);
    setError(null);
    try {
      const job = await api.createJob(video.video_id, options, idempotencyKey.current);
      navigate(`/jobs/${job.job_id}`, { state: { skipTransition: true } });
    } catch (err) {
      if (err instanceof ApiError && err.code === "JOB_ALREADY_ACTIVE" && typeof err.details.job_id === "string") {
        navigate(`/jobs/${err.details.job_id}`, { state: { skipTransition: true } });
        return;
      }
      setError(err instanceof Error ? err.message : "Could not start the analysis");
      setStarting(false);
    }
  };

  return (
    <div className="upload-page-container">
      <div className="page-header upload-page-header">
        <h1>Analyse a freight train video</h1>
        <p>Upload a video to detect, count and order the wagons. Processing runs on the server.</p>
      </div>

      {error && <Alert kind="error" title="Something went wrong">{error}</Alert>}

      {phase.kind === "idle" && (
        <>
          <div className="upload-card">
            <RailSchematic />
            <UploadDropzone onFile={onFile} />
          </div>
          <UploadCapabilities />
        </>
      )}

      {phase.kind === "uploading" && (
        <Card title="Uploading">
          <div className="stack" style={{ gap: 16 }}>
            <div className="row">
              <span>{phase.file.name}</span>
              <div className="spacer" />
              <span className="muted small">
                {formatBytes(phase.progress.loaded)} of {formatBytes(phase.progress.total)}
              </span>
            </div>
            <ProgressBar value={phase.progress.total ? (100 * phase.progress.loaded) / phase.progress.total : null} />
            <div className="row">
              <span className="muted small">
                {phase.progress.loaded >= phase.progress.total
                  ? "Checking the video on the server..."
                  : "Keep this page open until the upload finishes."}
              </span>
              <div className="spacer" />
              <button className="btn btn-small" onClick={() => handle.current?.abort()}>Cancel upload</button>
            </div>
          </div>
        </Card>
      )}

      {phase.kind === "uploaded" && (
        <Card title="Ready to analyse">
          <div className="stack">
            <dl className="meta-grid" style={{ margin: 0 }}>
              <div><dt>File</dt><dd>{phase.video.original_filename}</dd></div>
              <div><dt>Duration</dt><dd>{formatDuration(phase.video.duration_seconds)}</dd></div>
              <div><dt>Resolution</dt><dd>{phase.video.width} x {phase.video.height}</dd></div>
              <div><dt>Frame rate</dt><dd>{phase.video.fps ? `${phase.video.fps.toFixed(1)} fps` : "-"}</dd></div>
              <div><dt>Size</dt><dd>{formatBytes(phase.video.size_bytes)}</dd></div>
              <div><dt>Codec</dt><dd>{phase.video.codec ?? "-"}</dd></div>
            </dl>
            <JobOptionsForm
              value={options}
              onChange={(o) => {
                setOptions(o);
                idempotencyKey.current = newIdempotencyKey(); // different request -> new key
              }}
            />
            <div className="row">
              <button className="btn btn-primary" disabled={starting} onClick={() => startAnalysis(phase.video)}>
                {starting ? "Starting..." : "Analyse video"}
              </button>
              <button className="btn" disabled={starting} onClick={() => { setPhase({ kind: "idle" }); setOptions({}); }}>
                Choose another video
              </button>
            </div>
          </div>
        </Card>
      )}
    </div>
  );
}
