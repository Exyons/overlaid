/** Transport icons. Inline SVG so they inherit colour and need no network. */

export function PlayIcon() {
  return (
    <svg viewBox="0 0 16 16" width="15" height="15" aria-hidden="true">
      <path d="M4.5 2.6v10.8a.6.6 0 0 0 .93.5l8.1-5.4a.6.6 0 0 0 0-1L5.43 2.1a.6.6 0 0 0-.93.5Z"
            fill="currentColor" />
    </svg>
  )
}

export function PauseIcon() {
  return (
    <svg viewBox="0 0 16 16" width="15" height="15" aria-hidden="true">
      <rect x="4" y="2.5" width="3" height="11" rx="0.6" fill="currentColor" />
      <rect x="9" y="2.5" width="3" height="11" rx="0.6" fill="currentColor" />
    </svg>
  )
}
