import type { components } from "../../api/schema";

type PendingItem = components["schemas"]["PendingItem"];

/** Pre-filled comment the user can edit before confirming. */
export function defaultDecisionNote(pending: Pick<PendingItem, "event" | "title">): string {
  if (pending.event === "decision.brief_confirmed" || pending.title === "Confirm the brief") {
    return "Approved, please go ahead.";
  }
  if (pending.event === "decision.supplier_selected" || /award this order/i.test(pending.title)) {
    return "Awarding based on the comparison above.";
  }
  if (pending.event === "decision.vendor_recommended" || /recommend vendor/i.test(pending.title)) {
    return "Recommend based on the weighted evaluation; add a note if you prefer another vendor.";
  }
  return "";
}
