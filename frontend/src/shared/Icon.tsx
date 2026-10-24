import type { ReactNode } from "react";

const shapes = {
  info: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 11v6M12 7h.01" />
    </>
  ),
  archive: (
    <>
      <path d="M4 4h4v16H4zM10 4h4v16h-4zM16 5l3-1 4 15-3 1z" />
    </>
  ),
  review: (
    <>
      <rect x="4" y="4" width="16" height="16" rx="2" />
      <path d="m8 12 3 3 5-6" />
    </>
  ),
  tags: (
    <>
      <path d="m20 13-7 7-9-9V4h7l9 9Z" />
      <circle cx="8" cy="8" r="1" />
    </>
  ),
  settings: (
    <>
      <path d="M3 6h6m4 0h8M3 12h12m4 0h2M3 18h2m4 0h12" />
      <circle cx="11" cy="6" r="2" />
      <circle cx="17" cy="12" r="2" />
      <circle cx="7" cy="18" r="2" />
    </>
  ),
  plus: <path d="M12 5v14M5 12h14" />,
  search: (
    <>
      <circle cx="10.5" cy="10.5" r="6.5" />
      <path d="m16 16 5 5" />
    </>
  ),
  back: <path d="m11 5-7 7 7 7M4 12h16" />,
  arrow: <path d="M7 17 17 7M7 7h10v10" />,
  copy: (
    <>
      <rect x="8" y="8" width="12" height="13" rx="2" />
      <path d="M16 8V5a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h3" />
    </>
  ),
  locate: (
    <>
      <circle cx="12" cy="12" r="7" />
      <circle cx="12" cy="12" r="2" />
      <path d="M12 2v3m0 14v3M2 12h3m14 0h3" />
    </>
  ),
  document: (
    <>
      <path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9l-6-6Z" />
      <path d="M14 3v6h6M8 13h8M8 17h5" />
    </>
  ),
  logout: (
    <>
      <path d="M9 5H5v14h4m5-14 5 7-5 7M9 12h10" />
    </>
  ),
} satisfies Record<string, ReactNode>;

export type IconName = keyof typeof shapes;
export function Icon({ name }: { name: IconName }) {
  return (
    <svg
      className="ui-icon"
      width="18"
      height="18"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      {shapes[name]}
    </svg>
  );
}
