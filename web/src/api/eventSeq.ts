/** Numeric outbox sequence from a cursor id (`<stream>:<seq>`). */
export function parseStreamSeq(cursorId: string): number | null {
  const i = cursorId.lastIndexOf(":");
  if (i < 0) return null;
  const n = Number.parseInt(cursorId.slice(i + 1), 10);
  return Number.isFinite(n) ? n : null;
}

export function isDeltaEventType(type: string): boolean {
  return type === "agent.message.delta";
}
