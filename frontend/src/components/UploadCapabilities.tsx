export function UploadCapabilities() {
  return (
    <section className="capabilities-strip" aria-label="System capabilities">
      <div className="capability-card">
        <div className="capability-icon-wrap" aria-hidden="true">
          <svg
            className="capability-icon"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.75"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <path d="M4 7V4h3" />
            <path d="M17 4h3v3" />
            <path d="M20 17v3h-3" />
            <path d="M7 20H4v-3" />
            <rect x="7" y="8" width="10" height="7" rx="1" />
            <circle cx="9.5" cy="18" r="1.5" />
            <circle cx="14.5" cy="18" r="1.5" />
          </svg>
        </div>
        <div className="capability-content">
          <h3 className="capability-title">Rolling-stock detection</h3>
          <p className="capability-desc">Identifies locomotives and wagon classifications across video frames.</p>
        </div>
      </div>

      <div className="capability-card">
        <div className="capability-icon-wrap" aria-hidden="true">
          <svg
            className="capability-icon"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.75"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <line x1="3" y1="18" x2="21" y2="18" />
            <path d="M4 13h5v5H4z" />
            <path d="M11 13h5v5h-5z" />
            <path d="M18 13h2v5h-2z" />
            <path d="M12 3v7" />
            <polyline points="9 6 12 3 15 6" />
          </svg>
        </div>
        <div className="capability-content">
          <h3 className="capability-title">Wagon counting and ordering</h3>
          <p className="capability-desc">Tracks transit direction and logs each vehicle in passage sequence.</p>
        </div>
      </div>

      <div className="capability-card">
        <div className="capability-icon-wrap" aria-hidden="true">
          <svg
            className="capability-icon"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.75"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
            <polyline points="14 2 14 8 20 8" />
            <polyline points="9 14 11 16 15 12" />
          </svg>
        </div>
        <div className="capability-content">
          <h3 className="capability-title">Results review</h3>
          <p className="capability-desc">Inspect wagon crops, confidence scores, and export summary data.</p>
        </div>
      </div>
    </section>
  );
}
