import type { InstanceSnapshot } from "./jobStreamReducer";
import { messageComposerArtifacts } from "./workComposerHint";

export function hasOpenTaskRetry(snapshot: InstanceSnapshot): boolean {
  return snapshot.pending.some((p) => p.status === "open" && p.event === "task.retry");
}

export function showSendRfqsBar(snapshot: InstanceSnapshot): boolean {
  if (!snapshot.my_roles.includes("buyer")) return false;
  if (snapshot.state !== "rfq_sending" && snapshot.state !== "rfp_sending") return false;
  const drafts = messageComposerArtifacts(snapshot.artifacts);
  if (drafts.length === 0) return false;
  // A stale retry card must not block panel send; POST send-rfqs completes the step and clears retry.
  return true;
}

export function sendRfqsCopy(count: number): string {
  const noun = count === 1 ? "This outbound message" : `These ${count} outbound messages`;
  return `${noun} will go to the addresses in the tabs. Review the drafts, then approve and send.`;
}
