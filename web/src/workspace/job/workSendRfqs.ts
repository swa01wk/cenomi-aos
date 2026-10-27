import type { InstanceSnapshot } from "./jobStreamReducer";
import { messageComposerArtifacts } from "./workComposerHint";

export function showSendRfqsBar(snapshot: InstanceSnapshot): boolean {
  if (!snapshot.my_roles.includes("buyer")) return false;
  const drafts = messageComposerArtifacts(snapshot.artifacts);
  if (drafts.length === 0) return false;
  if (snapshot.state === "rfq_sending") return true;
  return snapshot.state === "awaiting_quotes";
}

export function sendRfqsCopy(count: number, state: string): string {
  const noun = count === 1 ? "This RFQ email" : `These ${count} RFQ emails`;
  if (state === "awaiting_quotes") {
    return `${noun} will be delivered through your configured mailbox (same supplier addresses as in the drafts). Use this if Sent in Gmail did not show all three.`;
  }
  return `${noun} will go to the supplier addresses in the tabs. Review the drafts, then approve and send.`;
}
