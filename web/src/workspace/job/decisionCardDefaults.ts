import type { components } from "../../api/schema";

type PendingItem = components["schemas"]["PendingItem"];

/** Pre-filled comment the user can edit before confirming. */
export function defaultDecisionNote(pending: Pick<PendingItem, "event" | "title">): string {
  if (pending.event === "decision.brief_confirmed" || pending.title === "Confirm the brief") {
    return "Approved, please go ahead.";
  }
  return "";
}
