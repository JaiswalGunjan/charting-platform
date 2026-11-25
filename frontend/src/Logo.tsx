/** Charting Lab's mark (also the browser-tab icon, public/favicon.svg): three candles and a rising trend line. */
export default function Logo({ size = 20 }: { size?: number }) {
  return (
    <svg className="logo" width={size} height={size} viewBox="0 0 64 64" aria-hidden="true">
      <rect width="64" height="64" rx="14" fill="var(--accent)" />
      <g stroke="#ffffff" strokeWidth="3" strokeLinecap="round">
        <line x1="17" y1="22" x2="17" y2="48" />
        <line x1="32" y1="14" x2="32" y2="42" />
        <line x1="47" y1="10" x2="47" y2="34" />
      </g>
      <rect x="12" y="28" width="10" height="14" rx="2" fill="#ffffff" />
      <rect x="27" y="20" width="10" height="15" rx="2" fill="#ffffff" opacity=".85" />
      <rect x="42" y="15" width="10" height="13" rx="2" fill="#ffffff" />
      <path d="M9 52 L25 44 L37 47 L55 33" fill="none" stroke="#7fe3c4" strokeWidth="4" strokeLinecap="round"
        strokeLinejoin="round" />
    </svg>
  );
}
