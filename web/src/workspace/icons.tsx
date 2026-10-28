import type { ReactNode } from "react";

function Icon({ size, strokeWidth = 2, children }: { size: number; strokeWidth?: number; children: ReactNode }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      style={{ flex: "none" }}
    >
      {children}
    </svg>
  );
}

export function SparkleIcon({ size = 22 }: { size?: number }) {
  return (
    <Icon size={size} strokeWidth={size < 18 ? 2.5 : 2}>
      <path d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9z" />
    </Icon>
  );
}

export function PlusIcon({ size = 16 }: { size?: number }) {
  return (
    <Icon size={size} strokeWidth={2.5}>
      <path d="M12 5v14M5 12h14" />
    </Icon>
  );
}

export function QueueIcon({ size = 18 }: { size?: number }) {
  return (
    <Icon size={size}>
      <path d="M8 6h13M8 12h13M8 18h13" />
      <path d="M3 6h.01M3 12h.01M3 18h.01" />
    </Icon>
  );
}

export function BriefcaseIcon({ size = 18 }: { size?: number }) {
  return (
    <Icon size={size}>
      <rect x="3" y="7" width="18" height="13" rx="2" />
      <path d="M9 7V5a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v2" />
    </Icon>
  );
}

export function CheckIcon({ size = 16 }: { size?: number }) {
  return (
    <Icon size={size} strokeWidth={2.5}>
      <path d="M5 12l5 5L20 7" />
    </Icon>
  );
}

export function ArrowUpIcon({ size = 18 }: { size?: number }) {
  return (
    <Icon size={size} strokeWidth={2.5}>
      <path d="M12 19V5M5 12l7-7 7 7" />
    </Icon>
  );
}

/** The Seat's mark: a gradient tile with a sparkle, and a status dot when `online` is given. */
export function SeatMark({ small = false, online }: { small?: boolean; online?: boolean }) {
  return (
    <span className={small ? "ws-seat-mark small" : "ws-seat-mark"} aria-hidden="true">
      <SparkleIcon size={small ? 14 : 22} />
      {online !== undefined && <span className={online ? "ws-seat-dot" : "ws-seat-dot off"} />}
    </span>
  );
}
