import type { ReactNode } from 'react';

// Jeu d'icônes SVG maison (style stroke 24px), sans dépendance externe.
export type IconName =
  | 'droplet'
  | 'chat'
  | 'alert'
  | 'school'
  | 'inbox'
  | 'file'
  | 'bell'
  | 'sliders'
  | 'search'
  | 'x'
  | 'check'
  | 'chevron-down'
  | 'sun'
  | 'moon'
  | 'command'
  | 'logout'
  | 'menu'
  | 'plus'
  | 'send'
  | 'arrow-right'
  | 'shield'
  | 'clock'
  | 'user';

const PATHS: Record<IconName, ReactNode> = {
  droplet: <path d="M12 3c3.2 4.1 6 7.2 6 10.6a6 6 0 1 1-12 0C6 10.2 8.8 7.1 12 3z" />,
  chat: <path d="M4 5h16a1 1 0 0 1 1 1v8a1 1 0 0 1-1 1H9l-5 4V6a1 1 0 0 1 1-1z" />,
  alert: (
    <>
      <path d="M12 4 2.8 20h18.4L12 4z" />
      <path d="M12 10v4" />
      <path d="M12 17.5h.01" />
    </>
  ),
  school: (
    <>
      <path d="M3 10 12 4l9 6" />
      <path d="M5 10v9h14v-9" />
      <path d="M10 19v-4h4v4" />
    </>
  ),
  inbox: (
    <>
      <path d="M3 13 5.5 5h13L21 13v6H3v-6z" />
      <path d="M3 13h6l1.5 2.5h3L15 13h6" />
    </>
  ),
  file: (
    <>
      <path d="M6 3h8l4 4v14H6V3z" />
      <path d="M14 3v4h4" />
      <path d="M9 12h6M9 16h6" />
    </>
  ),
  bell: (
    <>
      <path d="M6 9a6 6 0 1 1 12 0c0 5 2 6 2 6H4s2-1 2-6" />
      <path d="M10 20a2 2 0 0 0 4 0" />
    </>
  ),
  sliders: (
    <>
      <path d="M4 7h9M17 7h3M4 17h3M11 17h9" />
      <circle cx="15" cy="7" r="2" />
      <circle cx="9" cy="17" r="2" />
    </>
  ),
  search: (
    <>
      <circle cx="11" cy="11" r="7" />
      <path d="m20 20-3.5-3.5" />
    </>
  ),
  x: <path d="M6 6l12 12M18 6 6 18" />,
  check: <path d="m4 12.5 5 5L20 6.5" />,
  'chevron-down': <path d="m6 9 6 6 6-6" />,
  sun: (
    <>
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2v2.5M12 19.5V22M2 12h2.5M19.5 12H22M4.9 4.9l1.8 1.8M17.3 17.3l1.8 1.8M4.9 19.1l1.8-1.8M17.3 6.7l1.8-1.8" />
    </>
  ),
  moon: <path d="M20 13.5A8 8 0 1 1 10.5 4 6.5 6.5 0 0 0 20 13.5z" />,
  command: <path d="M9 9V6.5A2.5 2.5 0 1 0 6.5 9H9zm6 0V6.5a2.5 2.5 0 1 1 2.5 2.5H15zM9 15v2.5A2.5 2.5 0 1 1 6.5 15H9zm6 0v2.5a2.5 2.5 0 1 0 2.5-2.5H15z" />,
  logout: (
    <>
      <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
      <path d="m16 17 5-5-5-5" />
      <path d="M21 12H9" />
    </>
  ),
  menu: <path d="M4 6h16M4 12h16M4 18h16" />,
  plus: <path d="M12 5v14M5 12h14" />,
  send: (
    <>
      <path d="M22 2 11 13" />
      <path d="M22 2 15 22l-4-9-9-4 20-7z" />
    </>
  ),
  'arrow-right': (
    <>
      <path d="M4 12h16" />
      <path d="m14 6 6 6-6 6" />
    </>
  ),
  shield: (
    <>
      <path d="M12 3l7 3v5c0 5-3.4 8-7 9-3.6-1-7-4-7-9V6l7-3z" />
      <path d="m9 12 2 2 4-4" />
    </>
  ),
  clock: (
    <>
      <circle cx="12" cy="12" r="8.5" />
      <path d="M12 7v5l3.5 2" />
    </>
  ),
  user: (
    <>
      <circle cx="12" cy="8" r="4" />
      <path d="M4 21c1.5-3.5 4.5-5 8-5s6.5 1.5 8 5" />
    </>
  ),
};

export function Icon({ name, className = 'h-5 w-5' }: { name: IconName; className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden="true"
    >
      {PATHS[name]}
    </svg>
  );
}
