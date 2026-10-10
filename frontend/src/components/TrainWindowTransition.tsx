import { useEffect, useRef, useState } from "react";
import { useLocation } from "react-router-dom";

function getDestinationLabel(pathname: string): string {
  if (pathname === "/") return "Moving to Analyse video...";
  if (pathname === "/jobs") return "Moving to Jobs...";
  if (pathname.startsWith("/jobs/")) return "Opening job details...";
  return "Travelling...";
}

export function TrainWindowTransition() {
  const location = useLocation();
  const [active, setActive] = useState(false);
  const [label, setLabel] = useState("");
  const prevPath = useRef(location.pathname);
  const isFirstMount = useRef(true);
  const timeoutRef = useRef<number | null>(null);

  useEffect(() => {
    // Direct initial load or page refresh: do not show transition
    if (isFirstMount.current) {
      isFirstMount.current = false;
      prevPath.current = location.pathname;
      return;
    }

    // If pathname did not change (same route click or query param only)
    if (prevPath.current === location.pathname) {
      return;
    }

    // If navigation state explicitly requests skipping (e.g. analysis started from upload)
    if ((location.state as { skipTransition?: boolean } | null)?.skipTransition) {
      prevPath.current = location.pathname;
      return;
    }

    const currentDestLabel = getDestinationLabel(location.pathname);
    prevPath.current = location.pathname;
    setLabel(currentDestLabel);
    setActive(true);

    if (timeoutRef.current) {
      window.clearTimeout(timeoutRef.current);
    }

    // Complete the transition in ~520ms (fast, professional, non-blocking)
    timeoutRef.current = window.setTimeout(() => {
      setActive(false);
      timeoutRef.current = null;
    }, 540);

    return () => {
      if (timeoutRef.current) {
        window.clearTimeout(timeoutRef.current);
      }
    };
  }, [location.pathname, location.state]);

  if (!active) return null;

  return (
    <div
      className="train-window-overlay"
      role="status"
      aria-live="polite"
      aria-label={label}
    >
      <div className="train-window-backdrop" />
      <div className="train-window-container">
        {/* Exterior Train Window Bezel */}
        <div className="train-window-frame">
          <div className="train-window-pane">
            {/* Scenery Viewport with parallax layers moving right-to-left */}
            <div className="train-scenery-viewport">
              {/* Sky Background */}
              <div className="scenery-sky" />

              {/* Distant Hills / Mountains Layer */}
              <div className="scenery-layer scenery-hills" aria-hidden="true">
                <svg className="scenery-svg" viewBox="0 0 1200 160" preserveAspectRatio="none">
                  <path
                    d="M0 110 Q 150 40 300 95 T 600 80 T 900 105 T 1200 90 L 1200 160 L 0 160 Z"
                    fill="#627d98"
                    opacity="0.45"
                  />
                  <path
                    d="M0 125 Q 200 70 400 110 T 800 95 T 1200 120 L 1200 160 L 0 160 Z"
                    fill="#486581"
                    opacity="0.6"
                  />
                </svg>
                <svg className="scenery-svg" viewBox="0 0 1200 160" preserveAspectRatio="none">
                  <path
                    d="M0 110 Q 150 40 300 95 T 600 80 T 900 105 T 1200 90 L 1200 160 L 0 160 Z"
                    fill="#627d98"
                    opacity="0.45"
                  />
                  <path
                    d="M0 125 Q 200 70 400 110 T 800 95 T 1200 120 L 1200 160 L 0 160 Z"
                    fill="#486581"
                    opacity="0.6"
                  />
                </svg>
              </div>

              {/* Midground Trees & Countryside Terrain */}
              <div className="scenery-layer scenery-trees" aria-hidden="true">
                <svg className="scenery-svg" viewBox="0 0 1200 120" preserveAspectRatio="none">
                  <path
                    d="M0 80 Q 80 50 160 75 Q 240 45 320 80 T 640 70 T 960 75 T 1200 80 L 1200 120 L 0 120 Z"
                    fill="#334e68"
                    opacity="0.85"
                  />
                  {/* Tree clumps & silhouettes */}
                  <circle cx="120" cy="65" r="16" fill="#243b53" />
                  <circle cx="280" cy="62" r="18" fill="#243b53" />
                  <circle cx="460" cy="60" r="22" fill="#243b53" />
                  <circle cx="720" cy="64" r="17" fill="#243b53" />
                  <circle cx="980" cy="61" r="20" fill="#243b53" />
                  <circle cx="1140" cy="66" r="15" fill="#243b53" />
                </svg>
                <svg className="scenery-svg" viewBox="0 0 1200 120" preserveAspectRatio="none">
                  <path
                    d="M0 80 Q 80 50 160 75 Q 240 45 320 80 T 640 70 T 960 75 T 1200 80 L 1200 120 L 0 120 Z"
                    fill="#334e68"
                    opacity="0.85"
                  />
                  <circle cx="120" cy="65" r="16" fill="#243b53" />
                  <circle cx="280" cy="62" r="18" fill="#243b53" />
                  <circle cx="460" cy="60" r="22" fill="#243b53" />
                  <circle cx="720" cy="64" r="17" fill="#243b53" />
                  <circle cx="980" cy="61" r="20" fill="#243b53" />
                  <circle cx="1140" cy="66" r="15" fill="#243b53" />
                </svg>
              </div>

              {/* Foreground Trackside Speed Poles & Embankment */}
              <div className="scenery-layer scenery-poles" aria-hidden="true">
                <svg className="scenery-svg" viewBox="0 0 1000 80" preserveAspectRatio="none">
                  {/* Telegraph poles rushing past */}
                  <line x1="200" y1="20" x2="200" y2="80" stroke="#102a43" strokeWidth="4" />
                  <line x1="185" y1="28" x2="215" y2="28" stroke="#102a43" strokeWidth="2.5" />
                  <line x1="600" y1="20" x2="600" y2="80" stroke="#102a43" strokeWidth="4" />
                  <line x1="585" y1="28" x2="615" y2="28" stroke="#102a43" strokeWidth="2.5" />
                  {/* Ballast / gravel bed */}
                  <rect x="0" y="65" width="1000" height="15" fill="#1e293b" />
                </svg>
                <svg className="scenery-svg" viewBox="0 0 1000 80" preserveAspectRatio="none">
                  <line x1="200" y1="20" x2="200" y2="80" stroke="#102a43" strokeWidth="4" />
                  <line x1="185" y1="28" x2="215" y2="28" stroke="#102a43" strokeWidth="2.5" />
                  <line x1="600" y1="20" x2="600" y2="80" stroke="#102a43" strokeWidth="4" />
                  <line x1="585" y1="28" x2="615" y2="28" stroke="#102a43" strokeWidth="2.5" />
                  <rect x="0" y="65" width="1000" height="15" fill="#1e293b" />
                </svg>
              </div>

              {/* Subtle glass reflection & speed lines */}
              <div className="train-glass-glare" aria-hidden="true" />
              <div className="train-motion-blur" aria-hidden="true" />
            </div>
          </div>

          {/* Window Sill / Metal Trim Accent */}
          <div className="train-window-sill" />
        </div>

        {/* Clean Destination Indicator Badge */}
        <div className="train-window-status">
          <svg
            className="train-status-icon"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
          >
            <rect x="4" y="3" width="16" height="16" rx="2" />
            <path d="M4 11h16" />
            <path d="M12 3v8" />
            <circle cx="8" cy="15" r="1" />
            <circle cx="16" cy="15" r="1" />
          </svg>
          <span className="train-status-text">{label}</span>
        </div>
      </div>
    </div>
  );
}
