/** Знак-хлопушка. color — цвет знака, hole — цвет прорезей (фон). */
export function Logo({ size = 34, color = 'var(--c-accent)', hole = 'var(--c-bg)' }: { size?: number; color?: string; hole?: string }) {
  return (
    <svg width={size} height={(size * 104) / 120} viewBox="0 0 120 104" aria-hidden="true">
      <g transform="rotate(-12 60 30)">
        <rect x="10" y="20" width="100" height="18" rx="3" fill={color} />
        <polygon points="36,24 54,24 46,34 28,34" fill={hole} />
        <polygon points="68,24 86,24 78,34 60,34" fill={hole} />
      </g>
      <rect x="10" y="46" width="100" height="18" rx="3" fill={color} />
      <polygon points="36,50 54,50 46,60 28,60" fill={hole} />
      <polygon points="68,50 86,50 78,60 60,60" fill={hole} />
      <path d="M106 72 V98 H12" fill="none" stroke={color} strokeWidth="6" strokeLinecap="round" />
    </svg>
  )
}
