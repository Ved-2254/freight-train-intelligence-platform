// Types mirroring the backend API (/api/v1) and the pipeline result (schema_version 1.0).
// See documentation/backend_api.md and documentation/output_schema.md.

export type JobStatus = "queued" | "running" | "completed" | "failed" | "cancelled";

export const FINAL_STATUSES: JobStatus[] = ["completed", "failed", "cancelled"];

export interface ApiErrorBody {
  error: { code: string; message: string; details: Record<string, unknown> };
  request_id: string | null;
}

export interface Video {
  video_id: string;
  original_filename: string;
  size_bytes: number;
  content_type: string | null;
  status: "ready" | "deleted";
  duration_seconds: number | null;
  fps: number | null;
  width: number | null;
  height: number | null;
  frame_count: number | null;
  codec: string | null;
  uploaded_at: string;
  links: { self: string; create_job: string };
}

export interface JobOptions {
  target_fps?: number;
  confidence_threshold?: number;
  counting_mode?: "registry" | "line";
  line_position?: number;
  travel_axis?: "auto" | "x" | "y";
  write_video?: boolean;
}

export interface JobResultSummary {
  total_wagons: number;
  total_rolling_stock: number;
  excluded_classes: string[];
  type_counts: Record<string, number>;
  not_counted: number;
  sequence_completeness: string | null;
  uncertain_sequence_items: number | null;
  warnings: number;
  annotated_video_codec: string | null;
  browser_playable_video: boolean | null;
}

export interface JobLinks {
  self: string;
  video_source: string;
  cancel: string;
  results: string | null;
  annotated_video: string | null;
  exports: { json: string; csv: string; tracks_csv: string } | null;
}

export interface Job {
  job_id: string;
  video_id: string;
  video_filename: string | null;
  status: JobStatus;
  stage: string | null;
  progress_percent: number | null;
  message: string | null;
  cancel_requested: boolean;
  attempts: number;
  options: JobOptions;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  updated_at: string;
  error: { code: string; message: string } | null;
  result_summary: JobResultSummary | null;
  links: JobLinks;
}

export interface JobCreated {
  job_id: string;
  video_id: string;
  status: JobStatus;
  created_at: string;
  status_url: string;
  poll_interval_seconds: number;
}

export interface JobList {
  items: Job[];
  total: number;
  limit: number;
  offset: number;
}

export interface CancelResult {
  job_id: string;
  status: JobStatus;
  cancel_requested: boolean;
  message: string;
}

export interface ReadyStatus {
  status: "ready" | "not_ready";
  checks: Record<string, { ok: boolean; [key: string]: unknown }>;
  worker: { alive: boolean; count: number; busy?: number };
}

// ---- pipeline result (schema 1.0, subset used by the UI) ----

export interface SequenceItem {
  position: number;
  wagon_uid: string;
  class_name: string;
  class_confidence: number;
  reference_time: number | null;
  crossing_time: number | null;
  first_seen: number;
  uncertain: boolean;
  flags: string[];
}

export interface WagonRecord {
  wagon_uid: string;
  sequence_position: number | null;
  class_name: string;
  class_confidence: number;
  class_best_guess: string | null;
  class_distribution: Record<string, number>;
  count_status: string;
  uncertain: boolean;
  flags: string[];
  notes: string[];
  track_ids: number[];
  n_observations: number;
  first_seen_s: number;
  last_seen_s: number;
  reference_time_s: number | null;
  crossing_time_s: number | null;
}

export interface PipelineResult {
  schema_version: string;
  run_id: string;
  status: string;
  input: {
    path: string;
    width: number;
    height: number;
    fps: number | null;
    duration_seconds: number | null;
    codec: string | null;
  } | null;
  model: { model_file?: string; num_classes?: number; device?: string; class_names?: Record<string, string> };
  sampling: { sampled_frames?: number; decoded_frames?: number; effective_fps?: number; target_fps?: number };
  timing_seconds: Record<string, number>;
  counts: {
    mode: string;
    total_counted: number;
    wagons_only_total: number;
    excluded_classes: string[];
    type_counts: Record<string, number>;
    not_counted: number;
    tracker_ids_seen: number;
  } | null;
  sequence_info: {
    convention?: string;
    completeness?: string;
    uncertain_items?: number;
    order_string?: string;
    notes?: string[];
    travel_direction?: string;
  };
  sequence: SequenceItem[];
  wagons: WagonRecord[];
  warnings: string[];
  unresolved_identities: { type: string; track_ids: number[]; wagon_uids: string[]; detail: string }[];
}

export interface JobResults {
  job_id: string;
  video_id: string;
  status: string;
  summary: JobResultSummary;
  result: PipelineResult;
  links: JobLinks;
}
