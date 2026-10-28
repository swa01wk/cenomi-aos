import type { InstanceSnapshot } from "./jobStreamReducer";
import { messageComposerArtifacts } from "./workComposerHint";

export function hasOpenTaskRetry(snapshot: InstanceSnapshot): boolean {
  return snapshot.pending.some((p) => p.status === "open" && p.event === "task.retry");
}

export function showSendRfqsBar(snapshot: InstanceSnapshot): boolean {
  if (!snapshot.my_roles.includes("buyer")) return false;
  const drafts = messageComposerArtifacts(snapshot.artifacts);
  if (drafts.length === 0) return false;
  if (hasOpenTaskRetry(snapshot)) return false;
  return snapshot.state === "rfq_sending";
}

export function sendRfqsCopy(count: number): string {
  const noun = count === 1 ? "This RFQ email" : `These ${count} RFQ emails`;
  return `${noun} will go to the supplier addresses in the tabs. Review the drafts, then approve and send.`;
}
