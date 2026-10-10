export function RailSchematic() {
  return (
    <div className="rail-schematic" aria-hidden="true">
      <svg
        className="rail-schematic-svg"
        viewBox="0 0 760 76"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
      >
        {/* Sleeper cross-ties repeating along the track */}
        {Array.from({ length: 48 }).map((_, i) => (
          <line
            key={i}
            x1={10 + i * 16}
            y1={46}
            x2={10 + i * 16}
            y2={58}
            stroke="var(--border)"
            strokeWidth={2}
            strokeLinecap="round"
          />
        ))}

        {/* Dual Steel Rails */}
        <line x1={0} y1={48} x2={760} y2={48} stroke="var(--muted-light)" strokeWidth={1.5} opacity={0.65} />
        <line x1={0} y1={56} x2={760} y2={56} stroke="var(--muted-light)" strokeWidth={1.5} opacity={0.65} />

        {/* Optical Reference Line Marker (CV reference point) */}
        <line
          x1={520}
          y1={6}
          x2={520}
          y2={68}
          stroke="var(--accent)"
          strokeWidth={1.5}
          strokeDasharray="3 3"
        />
        {/* Top & Bottom Alignment Arrowheads */}
        <polygon points="520,2 516,7 524,7" fill="var(--accent)" />
        <polygon points="520,72 516,67 524,67" fill="var(--accent)" />
        {/* Optical Sensor Reference Line Label */}
        <text
          x={520}
          y={17}
          textAnchor="middle"
          fill="var(--accent)"
          fontSize={7.5}
          fontFamily="var(--font-mono)"
          fontWeight={600}
          letterSpacing="0.08em"
        >
          REFERENCE LINE
        </text>

        {/* Wagon 3: Container Flat (BLC) */}
        <g opacity={0.85}>
          {/* Flat platform chassis */}
          <rect x={70} y={42} width={100} height={5} rx={1} fill="var(--muted)" />
          {/* Container Block A */}
          <rect x={76} y={23} width={42} height={19} rx={1.5} fill="var(--surface)" stroke="var(--border)" strokeWidth={1} />
          <line x1={87} y1={23} x2={87} y2={42} stroke="var(--border)" strokeWidth={0.75} />
          <line x1={98} y1={23} x2={98} y2={42} stroke="var(--border)" strokeWidth={0.75} />
          {/* Container Block B */}
          <rect x={122} y={23} width={42} height={19} rx={1.5} fill="var(--surface)" stroke="var(--border)" strokeWidth={1} />
          <line x1={133} y1={23} x2={133} y2={42} stroke="var(--border)" strokeWidth={0.75} />
          <line x1={144} y1={23} x2={144} y2={42} stroke="var(--border)" strokeWidth={0.75} />
          {/* Wheels */}
          <circle cx={85} cy={48} r={3} fill="var(--text-secondary)" />
          <circle cx={99} cy={48} r={3} fill="var(--text-secondary)" />
          <circle cx={141} cy={48} r={3} fill="var(--text-secondary)" />
          <circle cx={155} cy={48} r={3} fill="var(--text-secondary)" />
          {/* Mechanical Coupler link */}
          <rect x={170} y={43} width={12} height={2.5} fill="var(--muted-light)" />
        </g>

        {/* Wagon 2: Open Gondola (BOXN) */}
        <g opacity={0.9}>
          {/* Open box wagon body */}
          <rect x={182} y={25} width={110} height={17} rx={1.5} fill="var(--surface)" stroke="var(--border)" strokeWidth={1} />
          {/* Vertical stiffener ribs */}
          <line x1={204} y1={25} x2={204} y2={42} stroke="var(--border)" strokeWidth={1} />
          <line x1={226} y1={25} x2={226} y2={42} stroke="var(--border)" strokeWidth={1} />
          <line x1={248} y1={25} x2={248} y2={42} stroke="var(--border)" strokeWidth={1} />
          <line x1={270} y1={25} x2={270} y2={42} stroke="var(--border)" strokeWidth={1} />
          {/* Underbody Chassis */}
          <rect x={180} y={42} width={114} height={5} rx={1} fill="var(--muted)" />
          {/* Wheels */}
          <circle cx={198} cy={48} r={3} fill="var(--text-secondary)" />
          <circle cx={212} cy={48} r={3} fill="var(--text-secondary)" />
          <circle cx={262} cy={48} r={3} fill="var(--text-secondary)" />
          <circle cx={276} cy={48} r={3} fill="var(--text-secondary)" />
          {/* Mechanical Coupler link */}
          <rect x={294} y={43} width={12} height={2.5} fill="var(--muted-light)" />
        </g>

        {/* Lead Unit: Locomotive (LOCO) */}
        <g>
          {/* Main Locomotive Body */}
          <rect x={306} y={19} width={128} height={23} rx={2} fill="var(--surface)" stroke="var(--border)" strokeWidth={1} />
          {/* Elevated Cab */}
          <path d="M372 19 L414 19 L414 42 L372 42 Z" fill="var(--accent-soft)" />
          {/* Cab Windows */}
          <rect x={380} y={22} width={11} height={7} rx={1} fill="var(--surface)" stroke="var(--border)" strokeWidth={0.8} />
          <rect x={396} y={22} width={11} height={7} rx={1} fill="var(--surface)" stroke="var(--border)" strokeWidth={0.8} />
          {/* Engine Exhaust Vent */}
          <rect x={330} y={15} width={9} height={4} rx={0.8} fill="var(--muted)" />
          <rect x={348} y={16} width={14} height={3} rx={0.8} fill="var(--muted)" />
          {/* Radiator Slits */}
          <line x1={322} y1={25} x2={322} y2={35} stroke="var(--border)" strokeWidth={1} strokeLinecap="round" />
          <line x1={327} y1={25} x2={327} y2={35} stroke="var(--border)" strokeWidth={1} strokeLinecap="round" />
          <line x1={332} y1={25} x2={332} y2={35} stroke="var(--border)" strokeWidth={1} strokeLinecap="round" />
          <line x1={337} y1={25} x2={337} y2={35} stroke="var(--border)" strokeWidth={1} strokeLinecap="round" />
          {/* Front Nose & Headlight */}
          <path d="M428 26 L434 29 L434 42 L428 42 Z" fill="var(--surface)" stroke="var(--border)" strokeWidth={1} />
          <circle cx={433} cy={31} r={1.8} fill="var(--warning)" />
          {/* Cowcatcher pilot wedge */}
          <polygon points="434,38 440,43 434,43" fill="var(--muted)" />
          {/* Underbody Chassis */}
          <rect x={304} y={42} width={132} height={5} rx={1} fill="var(--text-secondary)" />
          {/* Bogie Wheels rolling on rail */}
          <circle cx={322} cy={48} r={3.2} fill="var(--text)" stroke="var(--surface)" strokeWidth={0.8} />
          <circle cx={336} cy={48} r={3.2} fill="var(--text)" stroke="var(--surface)" strokeWidth={0.8} />
          <circle cx={350} cy={48} r={3.2} fill="var(--text)" stroke="var(--surface)" strokeWidth={0.8} />
          <circle cx={390} cy={48} r={3.2} fill="var(--text)" stroke="var(--surface)" strokeWidth={0.8} />
          <circle cx={404} cy={48} r={3.2} fill="var(--text)" stroke="var(--surface)" strokeWidth={0.8} />
          <circle cx={418} cy={48} r={3.2} fill="var(--text)" stroke="var(--surface)" strokeWidth={0.8} />
        </g>

        {/* Small Direction of Motion Arrow */}
        <g opacity={0.65}>
          <text
            x={600}
            y={32}
            fill="var(--muted)"
            fontSize={8}
            fontFamily="var(--font-mono)"
            letterSpacing="0.06em"
          >
            DIRECTION OF TRAVEL →
          </text>
        </g>
      </svg>
    </div>
  );
}
