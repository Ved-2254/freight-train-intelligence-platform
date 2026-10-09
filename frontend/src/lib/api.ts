// Small typed client for the backend API. All URLs returned by the API are relative
// ("/api/v1/..."); `apiUrl` turns them into absolute URLs for fetch, <video> and links.

import type {
  ApiErrorBody,
  CancelResult,
  Job,
  JobCreated,
  JobList,
  JobOptions,
  JobResults,
  JobStatus,
  ReadyStatus,
  Video,
} from "./types";

export const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/$/, "")
  ?? "http://127.0.0.1:8000";

export function apiUrl(path: string): string {
  return path.startsWith("http") ? path : `${API_BASE_URL}${path}`;
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: Record<string, unknown>;

  constructor(status: number, code: string, message: string, details: Record<string, unknown> = {}) {
    super(message);
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

/** Converts a failed response (or a network failure) into an ApiError with a readable message. */
export async function toApiError(response: Response | null, fallback = "Request failed"): Promise<ApiError> {
  if (!response) {
    return new ApiError(0, "NETWORK_ERROR", "Cannot reach the backend. Is it running?");
  }
  try {
    const body = (await response.json()) as ApiErrorBody;
    if (body?.error) {
      return new ApiError(response.status, body.error.code, body.error.message, body.error.details);
    }
  } catch {
    // not a JSON error body
  }
  return new ApiError(response.status, "HTTP_" + response.status, `${fallback} (HTTP ${response.status})`);
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(apiUrl(path), init);
  } catch {
    throw await toApiError(null);
  }
  if (!response.ok) {
    throw await toApiError(response);
  }
  return (await response.json()) as T;
}

export const api = {
  /** /ready answers 503 *with* a checks body when something is wrong; both are returned as data. */
  ready: async (): Promise<ReadyStatus> => {
    let response: Response;
    try {
      response = await fetch(apiUrl("/api/v1/ready"));
    } catch {
      throw await toApiError(null);
    }
    if (response.status !== 200 && response.status !== 503) {
      throw await toApiError(response);
    }
    return (await response.json()) as ReadyStatus;
  },

  getVideo: (videoId: string) => request<Video>(`/api/v1/videos/${videoId}`),

  createJob: (videoId: string, options: JobOptions, idempotencyKey: string) =>
    request<JobCreated>("/api/v1/jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json", "Idempotency-Key": idempotencyKey },
      body: JSON.stringify({ video_id: videoId, options }),
    }),

  listJobs: (params: { status?: JobStatus | ""; limit: number; offset: number }) => {
    const q = new URLSearchParams({ limit: String(params.limit), offset: String(params.offset) });
    if (params.status) q.set("status", params.status);
    return request<JobList>(`/api/v1/jobs?${q.toString()}`);
  },

  getJob: (jobId: string) => request<Job>(`/api/v1/jobs/${encodeURIComponent(jobId)}`),

  cancelJob: (jobId: string) =>
    request<CancelResult>(`/api/v1/jobs/${encodeURIComponent(jobId)}/cancel`, { method: "POST" }),

  getResults: (jobId: string) => request<JobResults>(`/api/v1/jobs/${encodeURIComponent(jobId)}/results`),
};

export function newIdempotencyKey(): string {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}
