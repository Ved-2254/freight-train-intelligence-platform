// Video upload with progress. fetch() cannot report upload progress, so this uses XMLHttpRequest.

import { ApiError, apiUrl } from "./api";
import type { ApiErrorBody, Video } from "./types";

export interface UploadProgress {
  loaded: number;
  total: number;
}

export interface UploadHandle {
  promise: Promise<Video>;
  abort: () => void;
}

export function uploadVideo(file: File, onProgress: (p: UploadProgress) => void): UploadHandle {
  const xhr = new XMLHttpRequest();
  const promise = new Promise<Video>((resolve, reject) => {
    xhr.open("POST", apiUrl("/api/v1/videos"));
    xhr.responseType = "json";
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) onProgress({ loaded: e.loaded, total: e.total });
    };
    xhr.onload = () => {
      if (xhr.status === 201) {
        resolve(xhr.response as Video);
        return;
      }
      const body = xhr.response as ApiErrorBody | null;
      if (body?.error) {
        reject(new ApiError(xhr.status, body.error.code, body.error.message, body.error.details));
      } else {
        reject(new ApiError(xhr.status, `HTTP_${xhr.status}`, `Upload failed (HTTP ${xhr.status})`));
      }
    };
    xhr.onerror = () => reject(new ApiError(0, "NETWORK_ERROR", "Cannot reach the backend. Is it running?"));
    xhr.onabort = () => reject(new ApiError(0, "UPLOAD_ABORTED", "Upload cancelled"));
    const form = new FormData();
    form.append("file", file, file.name);
    xhr.send(form);
  });
  return { promise, abort: () => xhr.abort() };
}
