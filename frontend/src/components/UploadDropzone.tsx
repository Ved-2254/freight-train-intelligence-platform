import { useRef, useState, type DragEvent } from "react";

export const ACCEPTED_EXTENSIONS = [".mp4", ".mov", ".avi", ".mkv"];
export const MAX_UPLOAD_BYTES = 2 * 1024 ** 3; // matches the backend default (FTIP_MAX_UPLOAD_BYTES)

/** Returns an error message, or null when the file can be uploaded. */
export function validateFile(file: File): string | null {
  const name = file.name.toLowerCase();
  if (!ACCEPTED_EXTENSIONS.some((ext) => name.endsWith(ext))) {
    return `Unsupported file type. Use ${ACCEPTED_EXTENSIONS.join(", ")}.`;
  }
  if (file.size === 0) return "The file is empty.";
  if (file.size > MAX_UPLOAD_BYTES) return "The file is larger than the 2 GB limit.";
  return null;
}

export function UploadDropzone({ onFile, disabled }: { onFile: (file: File) => void; disabled?: boolean }) {
  const input = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);

  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setDragging(false);
    if (disabled) return;
    const file = e.dataTransfer.files?.[0];
    if (file) onFile(file);
  };

  return (
    <div
      className={`dropzone${dragging ? " dragging" : ""}`}
      role="button"
      tabIndex={0}
      aria-disabled={disabled}
      onClick={() => !disabled && input.current?.click()}
      onKeyDown={(e) => {
        if ((e.key === "Enter" || e.key === " ") && !disabled) {
          e.preventDefault();
          input.current?.click();
        }
      }}
      onDragOver={(e) => {
        e.preventDefault();
        if (!disabled) setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={onDrop}
    >
      <div className="dropzone-icon-wrap">
        <svg
          className="dropzone-icon"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.75"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
          <polyline points="17 8 12 3 7 8" />
          <line x1="12" y1="3" x2="12" y2="15" />
        </svg>
      </div>

      <strong className="dropzone-title">Drop a train video here, or click to choose a file</strong>
      
      <p className="dropzone-sub">
        <span className="dropzone-tag">MP4, MOV, AVI or MKV</span>
        <span className="dropzone-sep">·</span>
        <span className="dropzone-tag">Up to 2 GB</span>
      </p>

      {/* Understated railway track-line motif at lower edge */}
      <div className="dropzone-track-motif" aria-hidden="true" />

      <input
        ref={input}
        type="file"
        accept={ACCEPTED_EXTENSIONS.join(",")}
        hidden
        data-testid="file-input"
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) onFile(file);
          e.target.value = ""; // allow choosing the same file again
        }}
      />
    </div>
  );
}
