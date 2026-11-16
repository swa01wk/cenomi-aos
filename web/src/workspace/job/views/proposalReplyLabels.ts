export type ProposalReplyContent = {
  supplier?: string;
  reply_kind?: string;
  question_lane?: string;
  acknowledged?: boolean;
  received_at?: string;
  reply_excerpt?: string;
  notes?: string;
};

export function proposalReplyHeading(content: ProposalReplyContent | undefined, version: number): string {
  const kind = content?.reply_kind;
  if (kind === "ack" || (content?.acknowledged && kind !== "proposal" && kind !== "question")) {
    return "Acknowledgement";
  }
  if (kind === "question") {
    const lane =
      content?.question_lane === "commercial"
        ? "Commercial"
        : content?.question_lane === "technical"
          ? "Technical"
          : null;
    const m = (content?.notes || "").match(/Clarification\s+(\d+)\s+of\s+(\d+)/i);
    const base = m ? `Vendor question ${m[1]} of ${m[2]}` : "Vendor clarification question";
    return lane ? `${base} (${lane})` : base;
  }
  if (kind === "proposal") return "Full commercial proposal";
  return `Inbound reply (v${version})`;
}

export function proposalClarificationDraftLabel(content: ProposalReplyContent | undefined): string {
  if (content?.question_lane === "commercial") {
    return "Draft answer (procurement)";
  }
  return "Draft answer (category manager)";
}

export function proposalClarificationDraftBody(notes: string | undefined): string {
  const text = (notes || "").trim();
  if (!text) return "";
  return text
    .replace(
      /^Clarification\s+\d+\s+of\s+\d+\s+\((commercial|technical)\)\s+—\s+draft for\s+[^:]+:\s*/i,
      "",
    )
    .replace(/^Clarification\s+\d+\s+of\s+\d+\s+—\s+draft for\s+[^:]+:\s*/i, "");
}
