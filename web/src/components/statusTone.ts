/** Fixed kernel / lifecycle state → visual tone. Unknown states use neutral. */
export type StatusTone = "ok" | "info" | "warn" | "bad" | "neutral";

const TONE: Record<string, StatusTone> = {
  ACTIVE: "ok",
  APPROVED: "info",
  AVAILABLE: "ok",
  BUSY: "warn",
  COMPLETED: "ok",
  CONFIGURED: "info",
  DRAFT: "neutral",
  KILLED: "bad",
  PAUSED: "warn",
  published: "ok",
  validated: "ok",
  publish_requested: "warn",
  invalid: "bad",
  retired: "neutral",
  WAITING_APPROVAL: "warn",
  passed: "ok",
  failed: "bad",
  running: "info",
  UNAVAILABLE: "neutral",
  TESTING: "info",
};

export function toneForState(state: string): StatusTone {
  return TONE[state] ?? "neutral";
}
