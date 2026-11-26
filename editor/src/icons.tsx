import type { ReactNode } from "react"

function Icon({ children, size = 16 }: { children: ReactNode; size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {children}
    </svg>
  )
}

export const icons = {
  plus: <Icon><path d="M8 3v10M3 8h10" /></Icon>,
  close: <Icon><path d="M4 4l8 8M12 4l-8 8" /></Icon>,
  check: <Icon><path d="M3 8.5l3.2 3L13 4.5" /></Icon>,
  send: <Icon><path d="M8 13V3M3.5 7.5L8 3l4.5 4.5" /></Icon>,
  stop: <Icon><rect x="4" y="4" width="8" height="8" rx="1.5" fill="currentColor" stroke="none" /></Icon>,
  play: <Icon><path d="M5 3.5v9l7.5-4.5z" fill="currentColor" stroke="none" /></Icon>,
  pause: <Icon><path d="M5 3.5v9M11 3.5v9" strokeWidth="2.2" /></Icon>,
  stepBack: <Icon><path d="M10.5 4L6 8l4.5 4M4.5 4v8" /></Icon>,
  stepForward: <Icon><path d="M5.5 4L10 8l-4.5 4M11.5 4v8" /></Icon>,
  prevShot: <Icon><path d="M8 4L4 8l4 4M12.5 4l-4 4 4 4" /></Icon>,
  nextShot: <Icon><path d="M8 4l4 4-4 4M3.5 4l4 4-4 4" /></Icon>,
  undo: <Icon><path d="M5.5 3L2.5 6l3 3M2.5 6h7a4 4 0 010 8H7" /></Icon>,
  redo: <Icon><path d="M10.5 3l3 3-3 3M13.5 6h-7a4 4 0 000 8H9" /></Icon>,
  download: <Icon><path d="M8 2.5v8M4.5 7.5L8 11l3.5-3.5M3 13.5h10" /></Icon>,
  sidebar: <Icon><rect x="2" y="3" width="12" height="10" rx="2" /><path d="M6 3v10" /></Icon>,
  stage: <Icon><rect x="2" y="3" width="12" height="10" rx="2" /><path d="M10 3v10" /></Icon>,
  lock: <Icon size={12}><rect x="3.5" y="7" width="9" height="6.5" rx="1.5" /><path d="M5.5 7V5a2.5 2.5 0 015 0v2" /></Icon>,
  chevron: <Icon size={12}><path d="M6 4l4 4-4 4" /></Icon>,
  film: <Icon><rect x="2" y="2.5" width="12" height="11" rx="2" /><path d="M5.5 2.5v11M10.5 2.5v11M2 8h12" /></Icon>,
  folder: <Icon><path d="M2 5a1.5 1.5 0 011.5-1.5h2.6l1.4 1.5h5A1.5 1.5 0 0114 6.5v5a1.5 1.5 0 01-1.5 1.5h-9A1.5 1.5 0 012 11.5z" /></Icon>,
  search: <Icon><circle cx="7" cy="7" r="4" /><path d="M10 10l3.5 3.5" /></Icon>,
  sun: <Icon><circle cx="8" cy="8" r="2.8" /><path d="M8 1.8v1.4M8 12.8v1.4M1.8 8h1.4M12.8 8h1.4M3.6 3.6l1 1M11.4 11.4l1 1M3.6 12.4l1-1M11.4 4.6l1-1" /></Icon>,
  eye: <Icon><path d="M1.5 8S4 3.5 8 3.5 14.5 8 14.5 8 12 12.5 8 12.5 1.5 8 1.5 8z" /><circle cx="8" cy="8" r="1.8" /></Icon>,
  revert: <Icon><path d="M3 3v4h4M3.4 7A5 5 0 113 9.5" /></Icon>,
  at: <Icon><circle cx="8" cy="8" r="2.4" /><path d="M10.4 5.8v3a1.5 1.5 0 003 0V8A5.5 5.5 0 1010 13" /></Icon>,
  trash: <Icon><path d="M3 4.5h10M6.5 4.5V3h3v1.5M4.5 4.5l.5 8.5h6l.5-8.5" /></Icon>,
  bolt: <Icon><path d="M8.8 1.8L3.5 9h4l-.8 5.2L12.5 7h-4z" /></Icon>,
}

/** The mark: a raven's head, drawn once here. */
export function Mark({ size = 20 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true">
      <path d="M3 13.5C3 8 7 4 12.5 4c3 0 5 1.2 6.2 3.2L22 8.5l-3 1.6c-.3 5.5-3.800 9.900-9.500 9.900H6l2-3.200C5 16 3 15.500 3 13.500z" fill="currentColor" />
      <circle cx="13.6" cy="8.6" r="1.1" fill="var(--bg)" />
    </svg>
  )
}

export function Spinner() {
  return <span className="spinner" role="status" aria-label="Working" />
}
