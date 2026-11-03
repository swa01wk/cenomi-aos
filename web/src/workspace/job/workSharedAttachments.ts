import type { InstanceSnapshot } from "./jobStreamReducer";
import { messageComposerArtifacts } from "./workComposerHint";

const RFQ_ATTACHMENT_STATES = new Set(["rfq_drafting", "rfq_sending"]);

export function showSharedAttachmentsBar(snapshot: InstanceSnapshot): boolean {
  if (!snapshot.my_roles.includes("buyer")) return false;
  if (!RFQ_ATTACHMENT_STATES.has(snapshot.state)) return false;
  return messageComposerArtifacts(snapshot.artifacts).length > 0;
}

export function formatAttachmentSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
