import type { MessageDelta } from "../types";

/** Apply deltas in arrival order; skip any with seq ≤ the last applied seq. */
export function joinDeltas(deltas: MessageDelta[]): string {
  let lastSeq = -1;
  let out = "";
  for (const d of deltas) {
    if (d.seq <= lastSeq) continue;
    lastSeq = d.seq;
    out += d.text;
  }
  return out;
}
