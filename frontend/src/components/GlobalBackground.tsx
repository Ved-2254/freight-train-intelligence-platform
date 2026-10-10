const SLEEPER_T_VALUES = [
  0.06, 0.1, 0.14, 0.18, 0.23, 0.28, 0.34, 0.4, 0.47, 0.54, 0.62, 0.7, 0.78, 0.86, 0.94, 1.0,
];

const MAST_T_VALUES = [0.12, 0.26, 0.44, 0.68, 0.96];

export function GlobalBackground() {
  // Pre-calculate catenary contact wire path points across masts
  const wirePoints = MAST_T_VALUES.map((t) => {
    const t2 = t * t;
    const inv = 1 - t;
    const inv2 = inv * inv;
    const two_inv_t = 2 * inv * t;

    const xl = inv2 * 910 + two_inv_t * 360 + t2 * -60;
    const xr = inv2 * 945 + two_inv_t * 580 + t2 * 320;
    const y = inv2 * 215 + two_inv_t * 320 + t2 * 480;
    const mastHeight = 85 + t * 230;

    return {
      x: xl + (xr - xl) * 0.45,
      y: y - mastHeight + 16,
    };
  });

  const wirePathD = wirePoints.reduce((acc, pt, idx) => {
    if (idx === 0) return `M ${pt.x.toFixed(1)} ${pt.y.toFixed(1)}`;
    const prev = wirePoints[idx - 1];
    const midX = (prev.x + pt.x) / 2;
    const midY = (prev.y + pt.y) / 2 + 3; // subtle physical wire sag
    return `${acc} Q ${midX.toFixed(1)} ${midY.toFixed(1)} ${pt.x.toFixed(1)} ${pt.y.toFixed(1)}`;
  }, "");

  return (
    <div className="app-ambient-bg" aria-hidden="true">
      {/* Generous engineering grid with soft radial mask clearing the center */}
      <div className="ambient-grid" />

      {/* Atmospheric minimal track perspective motif anchored at lower periphery */}
      <svg
        className="ambient-track-svg"
        viewBox="0 0 1600 480"
        preserveAspectRatio="xMinYMax meet"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
      >
        <defs>
          <linearGradient id="ambient-track-fade" x1="0" y1="1" x2="0.75" y2="0.25">
            <stop offset="0%" stopColor="#fff" stopOpacity="0.85" />
            <stop offset="35%" stopColor="#fff" stopOpacity="0.55" />
            <stop offset="70%" stopColor="#fff" stopOpacity="0.15" />
            <stop offset="100%" stopColor="#fff" stopOpacity="0" />
          </linearGradient>
          <mask id="ambient-track-mask">
            <rect width="1600" height="480" fill="url(#ambient-track-fade)" />
          </mask>
        </defs>

        <g mask="url(#ambient-track-mask)">
          {/* Sleepers (Railway Cross-Ties in perspective) */}
          {SLEEPER_T_VALUES.map((t, idx) => {
            const t2 = t * t;
            const inv = 1 - t;
            const inv2 = inv * inv;
            const two_inv_t = 2 * inv * t;

            const xl = inv2 * 910 + two_inv_t * 360 + t2 * -60;
            const xr = inv2 * 945 + two_inv_t * 580 + t2 * 320;
            const y = inv2 * 215 + two_inv_t * 320 + t2 * 480;
            const spread = (xr - xl) * 0.08;

            return (
              <line
                key={`tie-${idx}`}
                x1={Number((xl - spread).toFixed(1))}
                y1={Number(y.toFixed(1))}
                x2={Number((xr + spread).toFixed(1))}
                y2={Number(y.toFixed(1))}
                stroke="var(--bg-track-sleeper)"
                strokeWidth={Number((1.2 + t * 3.6).toFixed(1))}
                strokeLinecap="round"
                opacity={Number((0.55 + t * 0.4).toFixed(2))}
              />
            );
          })}

          {/* Left Steel Rail (Dual edge) */}
          <path
            d="M -60 480 Q 360 320 910 215"
            stroke="var(--bg-track-stroke)"
            strokeWidth="2.5"
            strokeLinecap="round"
          />
          <path
            d="M -54 484 Q 364 322 911 216"
            stroke="var(--bg-track-stroke)"
            strokeWidth="1"
            opacity="0.6"
          />

          {/* Right Steel Rail (Dual edge) */}
          <path
            d="M 320 480 Q 580 320 945 215"
            stroke="var(--bg-track-stroke)"
            strokeWidth="2.5"
            strokeLinecap="round"
          />
          <path
            d="M 326 484 Q 584 322 946 216"
            stroke="var(--bg-track-stroke)"
            strokeWidth="1"
            opacity="0.6"
          />

          {/* Faint Electrification Catenary Masts on Outer Flank */}
          {MAST_T_VALUES.map((t, idx) => {
            const t2 = t * t;
            const inv = 1 - t;
            const inv2 = inv * inv;
            const two_inv_t = 2 * inv * t;

            const xl = inv2 * 910 + two_inv_t * 360 + t2 * -60;
            const xr = inv2 * 945 + two_inv_t * 580 + t2 * 320;
            const y = inv2 * 215 + two_inv_t * 320 + t2 * 480;

            const xBase = xl - (xr - xl) * 0.42;
            const mastHeight = 85 + t * 230;
            const yTop = y - mastHeight;
            const xArmEnd = xl + (xr - xl) * 0.45;

            return (
              <g key={`mast-${idx}`} opacity={Number((0.35 + t * 0.45).toFixed(2))}>
                {/* Vertical Pole */}
                <line
                  x1={Number(xBase.toFixed(1))}
                  y1={Number(y.toFixed(1))}
                  x2={Number(xBase.toFixed(1))}
                  y2={Number(yTop.toFixed(1))}
                  stroke="var(--bg-track-wire)"
                  strokeWidth={Number((1 + t * 1.5).toFixed(1))}
                />
                {/* Horizontal Cantilever Arm */}
                <line
                  x1={Number(xBase.toFixed(1))}
                  y1={Number((yTop + 12).toFixed(1))}
                  x2={Number(xArmEnd.toFixed(1))}
                  y2={Number((yTop + 16).toFixed(1))}
                  stroke="var(--bg-track-wire)"
                  strokeWidth={Number((0.8 + t * 0.8).toFixed(1))}
                />
                {/* Diagonal Strut */}
                <line
                  x1={Number(xBase.toFixed(1))}
                  y1={Number((yTop + 28).toFixed(1))}
                  x2={Number((xBase + (xArmEnd - xBase) * 0.55).toFixed(1))}
                  y2={Number((yTop + 14).toFixed(1))}
                  stroke="var(--bg-track-wire)"
                  strokeWidth="0.8"
                />
              </g>
            );
          })}

          {/* Catenary Wire along Masts */}
          {wirePathD && (
            <path
              d={wirePathD}
              stroke="var(--bg-track-wire)"
              strokeWidth="0.9"
              fill="none"
              opacity="0.65"
            />
          )}
        </g>
      </svg>
    </div>
  );
}
