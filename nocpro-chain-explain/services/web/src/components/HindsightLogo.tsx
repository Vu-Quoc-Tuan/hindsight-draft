interface HindsightLogoProps {
  size?: number
  className?: string
  animated?: boolean
}

export function HindsightLogo({
  size = 36,
  className = '',
  animated = false,
}: HindsightLogoProps) {
  return (
    <div
      className={`relative inline-flex items-center justify-center shrink-0 select-none ${className}`}
      style={{ width: size, height: size }}
    >
      <svg
        viewBox="0 0 64 64"
        width={size}
        height={size}
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
        className="w-full h-full drop-shadow-md"
      >
        <defs>
          {/* Background Squircle Gradient */}
          <linearGradient id="logoBgGrad" x1="0" y1="0" x2="64" y2="64" gradientUnits="userSpaceOnUse">
            <stop offset="0%" stopColor="#0f172a" />
            <stop offset="100%" stopColor="#030712" />
          </linearGradient>

          {/* Lens Rim Coral to Cyan Gradient */}
          <linearGradient id="logoLensRim" x1="13" y1="13" x2="40" y2="40" gradientUnits="userSpaceOnUse">
            <stop offset="0%" stopColor="#f43f5e" />
            <stop offset="45%" stopColor="#fb7185" />
            <stop offset="80%" stopColor="#38bdf8" />
            <stop offset="100%" stopColor="#0284c7" />
          </linearGradient>

          {/* Magnifier Handle Gradient */}
          <linearGradient id="logoHandleGrad" x1="36" y1="36" x2="56" y2="56" gradientUnits="userSpaceOnUse">
            <stop offset="0%" stopColor="#f43f5e" />
            <stop offset="35%" stopColor="#e11d48" />
            <stop offset="100%" stopColor="#0369a1" />
          </linearGradient>

          {/* Glass Lens Optical Gradient */}
          <radialGradient id="logoGlassGlow" cx="26.5" cy="26.5" r="14" gradientUnits="userSpaceOnUse">
            <stop offset="0%" stopColor="#38bdf8" stopOpacity="0.4" />
            <stop offset="60%" stopColor="#0284c7" stopOpacity="0.15" />
            <stop offset="100%" stopColor="#0f172a" stopOpacity="0.65" />
          </radialGradient>

          {/* Central Root Cause Core Spark */}
          <radialGradient id="logoNodeGlow" cx="26.5" cy="26.5" r="5" gradientUnits="userSpaceOnUse">
            <stop offset="0%" stopColor="#ffffff" />
            <stop offset="30%" stopColor="#67e8f9" />
            <stop offset="70%" stopColor="#0284c7" stopOpacity="0.8" />
            <stop offset="100%" stopColor="#0284c7" stopOpacity="0" />
          </radialGradient>

          {/* Lens Clip Circle */}
          <clipPath id="logoLensClip">
            <circle cx="26.5" cy="26.5" r="13.5" />
          </clipPath>
        </defs>

        {/* 1. Base Squircle Badge with Sleek Cyber Border */}
        <rect
          x="2"
          y="2"
          width="60"
          height="60"
          rx="15"
          fill="url(#logoBgGrad)"
          stroke="#1e293b"
          strokeWidth="1.5"
        />
        <rect
          x="2"
          y="2"
          width="60"
          height="60"
          rx="15"
          fill="none"
          stroke="url(#logoLensRim)"
          strokeWidth="1"
          strokeOpacity="0.3"
        />

        {/* 2. Raw Alarm Chain Outside Lens (Diagonal at -45 degrees) */}
        <g transform="rotate(-45 26.5 26.5)">
          {/* Top-Right Link entering lens */}
          <rect
            x="2"
            y="22"
            width="18"
            height="9"
            rx="4.5"
            fill="none"
            stroke="#475569"
            strokeWidth="2.5"
            opacity="0.7"
          />
          {/* Bottom-Left Link leaving lens */}
          <rect
            x="33"
            y="22"
            width="18"
            height="9"
            rx="4.5"
            fill="none"
            stroke="#475569"
            strokeWidth="2.5"
            opacity="0.7"
          />
        </g>

        {/* 3. Magnifying Glass Handle */}
        <path
          d="M 36.5 36.5 L 53.5 53.5"
          stroke="url(#logoHandleGrad)"
          strokeWidth="5.5"
          strokeLinecap="round"
        />
        <path
          d="M 37.5 37.5 L 43.5 43.5"
          stroke="#fda4af"
          strokeWidth="2"
          strokeLinecap="round"
          opacity="0.8"
        />

        {/* 4. Inside the Magnifying Glass (Deep Inspection of Alarm Chain) */}
        <g clipPath="url(#logoLensClip)">
          {/* Optical Glass Lens Atmosphere */}
          <circle cx="26.5" cy="26.5" r="13.5" fill="url(#logoGlassGlow)" />

          {/* Diagnostic Crosshair & Radar Grid */}
          <line
            x1="13"
            y1="26.5"
            x2="40"
            y2="26.5"
            stroke="#38bdf8"
            strokeWidth="0.75"
            strokeDasharray="2 2"
            strokeOpacity="0.45"
          />
          <line
            x1="26.5"
            y1="13"
            x2="26.5"
            y2="40"
            stroke="#38bdf8"
            strokeWidth="0.75"
            strokeDasharray="2 2"
            strokeOpacity="0.45"
          />

          {/* Magnified Chain Links (Illuminated & Sharp) */}
          <g transform="rotate(-45 26.5 26.5)">
            {/* The Central Interlocking Link */}
            <rect
              x="16"
              y="20.5"
              width="21"
              height="12"
              rx="6"
              fill="#0284c7"
              fillOpacity="0.28"
              stroke="#38bdf8"
              strokeWidth="2.8"
            />
            {/* Inner loop glowing coral core */}
            <rect
              x="19"
              y="23"
              width="15"
              height="7"
              rx="3.5"
              fill="none"
              stroke="#f43f5e"
              strokeWidth="1.8"
              opacity="0.95"
            />
            {/* Intersecting links passing through the loop */}
            <path
              d="M 12 25 L 18 25"
              stroke="#38bdf8"
              strokeWidth="2.8"
              strokeLinecap="round"
            />
            <path
              d="M 35 25 L 41 25"
              stroke="#38bdf8"
              strokeWidth="2.8"
              strokeLinecap="round"
            />
          </g>

          {/* Root Cause Spark / Focal Point in Center */}
          <circle cx="26.5" cy="26.5" r="4.5" fill="url(#logoNodeGlow)" />
          <circle
            cx="26.5"
            cy="26.5"
            r="1.8"
            fill="#ffffff"
            className={animated ? 'animate-ping' : ''}
          />

          {/* Diagonal Glass Reflection Highlight */}
          <path
            d="M 16 22 A 12 12 0 0 1 34 16 A 11 11 0 0 0 19 25 Z"
            fill="#ffffff"
            fillOpacity="0.24"
          />
        </g>

        {/* 5. Glowing Rim of the Lens */}
        <circle
          cx="26.5"
          cy="26.5"
          r="13.5"
          fill="none"
          stroke="url(#logoLensRim)"
          strokeWidth="3"
        />
        <circle
          cx="26.5"
          cy="26.5"
          r="15"
          fill="none"
          stroke="#f43f5e"
          strokeWidth="0.75"
          strokeOpacity="0.4"
        />

        {/* Handle Connector Ring */}
        <circle cx="36.5" cy="36.5" r="2.8" fill="#f43f5e" />
      </svg>
    </div>
  )
}
