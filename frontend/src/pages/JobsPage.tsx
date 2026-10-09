import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Alert, StatusBadge } from "../components/common";
import { api } from "../lib/api";
import { formatDateTime, stageLabel } from "../lib/format";
import { usePolling } from "../lib/usePolling";
import type { JobList, JobStatus } from "../lib/types";

const PAGE_SIZE = 15;

export function JobsPage() {
  const [status, setStatus] = useState<JobStatus | "">("");
  const [offset, setOffset] = useState(0);
  const [data, setData] = useState<JobList | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setData(await api.listJobs({ status, limit: PAGE_SIZE, offset }));
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load jobs");
    }
  }, [status, offset]);

  useEffect(() => { void load(); }, [load]); // reload at once when the filter or page changes

  // Refresh every 3 s while any listed job is still active, otherwise every 15 s.
  const active = data?.items.some((j) => j.status === "queued" || j.status === "running") ?? false;
  usePolling(load, active ? 3000 : 15000, true);

  const page = Math.floor(offset / PAGE_SIZE) + 1;
  const pages = data ? Math.max(1, Math.ceil(data.total / PAGE_SIZE)) : 1;

  return (
    <div className="stack">
      <div className="page-header row">
        <div>
          <h1>Jobs</h1>
          <p>All processing jobs, newest first.</p>
        </div>
        <div className="spacer" />
        <select
          aria-label="Filter by status"
          value={status}
          onChange={(e) => { setStatus(e.target.value as JobStatus | ""); setOffset(0); }}
        >
          <option value="">All statuses</option>
          <option value="queued">Queued</option>
          <option value="running">Running</option>
          <option value="completed">Completed</option>
          <option value="failed">Failed</option>
          <option value="cancelled">Cancelled</option>
        </select>
        <Link className="btn btn-primary" to="/">New analysis</Link>
      </div>

      {error && <Alert kind="error" title="Could not load jobs">{error}</Alert>}

      <section className="card" style={{ padding: 0 }}>
        {data && data.items.length === 0 ? (
          <div className="empty">
            No jobs yet. <Link to="/">Upload a video</Link> to start.
          </div>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Video</th>
                  <th>Status</th>
                  <th>Progress</th>
                  <th>Wagons</th>
                  <th>Created</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {data?.items.map((job) => (
                  <tr key={job.job_id}>
                    <td>{job.video_filename ?? <span className="mono muted">{job.video_id}</span>}</td>
                    <td><StatusBadge status={job.status} /></td>
                    <td className="muted">
                      {job.status === "running"
                        ? `${stageLabel(job.stage)}${job.progress_percent != null ? `, ${Math.round(job.progress_percent)}%` : ""}`
                        : job.status === "failed" || job.status === "cancelled"
                          ? job.error?.message ?? "-"
                          : job.status === "queued" ? "Waiting" : "Done"}
                    </td>
                    <td className="num">{job.result_summary ? job.result_summary.total_wagons : "-"}</td>
                    <td className="muted">{formatDateTime(job.created_at)}</td>
                    <td><Link to={`/jobs/${job.job_id}`}>Open</Link></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {data && data.total > PAGE_SIZE && (
        <div className="pagination">
          <span className="muted small">Page {page} of {pages}</span>
          <button className="btn btn-small" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>
            Previous
          </button>
          <button className="btn btn-small" disabled={offset + PAGE_SIZE >= data.total} onClick={() => setOffset(offset + PAGE_SIZE)}>
            Next
          </button>
        </div>
      )}
    </div>
  );
}
