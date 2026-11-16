import { specialistAwaitingReply } from "./conversationDisplay";
import type { InstanceSnapshot } from "./jobStreamReducer";
import { messageComposerArtifacts } from "./workComposerHint";

export type StepGuide = {
  kind: "action" | "wait" | "progress" | "complete" | "notice";
  title: string;
  detail: string;
  footnote?: string;
};

/** Title or id suggests a formal RFP even when routing picked Quick Quote. */
export function looksLikeFormalRfpJob(snapshot: InstanceSnapshot): boolean {
  const hay = `${snapshot.title ?? ""} ${snapshot.instance_id ?? ""}`.toLowerCase();
  return (
    /\brfp\b/.test(hay) ||
    /marketing website|web portal|website redesign|formal rfp|master rfp/.test(hay)
  );
}

/** Shown on Quick Quote jobs that read like an RFP so users know where the doc is and why CDO is not involved. */
export function quickQuoteRfpMisrouteNotice(snapshot: InstanceSnapshot): StepGuide | null {
  if (snapshot.workflow !== "quick_quote" || snapshot.state === "closed") return null;
  if (!looksLikeFormalRfpJob(snapshot)) return null;

  let nextOnThisPath =
    "After the brief is confirmed, confirm the shortlist, then review RFQ email drafts — there is no Master RFP tab on Quick Quote.";
  if (snapshot.state === "shortlisting" || snapshot.state === "rfq_drafting" || snapshot.state === "rfq_sending") {
    nextOnThisPath =
      "Next on this job: confirm the shortlist (if not done), then approve RFQ emails to suppliers. CDO approval is not part of Quick Quote.";
  } else if (snapshot.state === "awaiting_quotes" || snapshot.state === "comparison") {
    nextOnThisPath = "This job continues with supplier quotes and award — not master RFP or CDO sign-off.";
  }

  return {
    kind: "notice",
    title: `Quick Quote (${snapshot.instance_id}) — not the full RFP path`,
    detail: `This job was created as Quick Quote (${snapshot.instance_id}). The workflow cannot change — you will not get a Master RFP tab or CDO approval here. ${nextOnThisPath} To run the full RFP path, open People → Noor Al-Rashid and send a new message (or + New job with “formal RFP…” wording). Confirm the new id starts with RFP- before you continue.`,
  };
}

function cdoMasterRfpReviewOpen(snapshot: InstanceSnapshot): boolean {
  return snapshot.pending.some(
    (p) => p.status === "open" && p.event === "decision.master_rfp_confirmed",
  );
}

function masterRfpAwaitingCdoGuide(snapshot: InstanceSnapshot, openPendingForYou: number): StepGuide | null {
  if (snapshot.workflow !== "sourcing_rfp" || openPendingForYou > 0) return null;
  const cdoPending = snapshot.pending.some(
    (p) => p.status === "open" && /approve master rfp/i.test(p.title ?? ""),
  );
  if (!cdoPending && snapshot.state !== "master_rfp_drafting") return null;
  const masterReady = snapshot.artifacts.some(
    (a) => a.artifact_type === "master_rfp" && a.latest_version >= 1,
  );
  if (!masterReady && !cdoPending) return null;
  return {
    kind: "wait",
    title: "Next: CDO approves the master RFP",
    detail:
      "Open the Master RFP tab in the work panel — that is the shareable document. Samir Al-Farsi must sign in as CDO and use Approve master RFP in the thread before vendor invitation emails are drafted.",
  };
}

/** Stage guide for the work panel (no duplicate action cards). */
export function workPanelStageGuide(
  snapshot: InstanceSnapshot,
  agentBusy: boolean,
): StepGuide | null {
  if (snapshot.state === "closed") return null;
  if (snapshot.state === "rfq_sending") return null;
  const openPendingForYou = snapshot.pending.filter((p) => p.status === "open").length;
  const guide = jobStepGuide(snapshot, { agentBusy, openPendingForYou });
  if (!guide || guide.kind === "action") return null;
  return compactWorkPanelGuide(guide, snapshot);
}

function compactWorkPanelGuide(guide: StepGuide, snapshot: InstanceSnapshot): StepGuide {
  if (snapshot.state !== "awaiting_quotes") {
    return { ...guide, footnote: undefined };
  }
  const invited = snapshot.artifacts.filter((a) => a.artifact_type === "rfq_email").length || 3;
  const windowHint = formatDeadlineHintForSnapshot(snapshot);
  if (guide.kind === "wait") {
    return {
      kind: "wait",
      title: "Waiting for replies",
      detail: `${invited} RFQs sent.${windowHint}`,
    };
  }
  if (guide.kind === "progress" && guide.title.includes("Supplier replies")) {
    return {
      kind: "progress",
      title: guide.title,
      detail: `${guide.detail.split(".")[0]}.${windowHint}`,
    };
  }
  return { ...guide, footnote: undefined };
}

export function stageGuideIsLive(guide: StepGuide, workflowState: string): boolean {
  if (guide.kind === "progress") return true;
  if (guide.kind === "wait" && workflowState === "awaiting_quotes") return true;
  return false;
}

export function replyWindowSecondsLeft(iso: string | undefined): number | null {
  if (!iso) return null;
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return null;
  return Math.max(0, Math.round((t - Date.now()) / 1000));
}

export function formatReplyWindowShort(iso: string | undefined): string {
  const secs = replyWindowSecondsLeft(iso);
  if (secs == null) return "";
  if (secs <= 0) return "window ended";
  if (secs < 120) return `${secs < 10 ? secs.toFixed(1) : String(Math.round(secs))}s left`;
  return `${Math.round(secs / 60)}m left`;
}

export function formatReplyWindowHint(iso: string | undefined): string {
  if (!iso) return "";
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return "";
  const secs = Math.max(0, Math.round((t - Date.now()) / 1000));
  if (secs <= 0) return " Reply window just ended.";
  if (secs < 120) {
    const s = secs < 10 ? secs.toFixed(1) : String(Math.round(secs));
    return ` Reply window ~${s}s (until ${new Date(t).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}).`;
  }
  const mins = Math.round(secs / 60);
  return ` Reply window ~${mins} min (until ${new Date(t).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}).`;
}

function formatDeadlineHintForSnapshot(snapshot: InstanceSnapshot): string {
  const briefM = snapshot.vendor_reply_window_minutes ?? 1.5;
  const maxSec = Math.max(Math.round(briefM * 60 * 1.5), 120);
  const left = replyWindowSecondsLeft(snapshot.quote_deadline_at);
  if (left == null || left > maxSec) {
    return ` ~${briefM} min (from your brief).`;
  }
  return formatReplyWindowHint(snapshot.quote_deadline_at);
}

function awaitingQuotesGuide(snapshot: InstanceSnapshot): StepGuide {
  const quotes = quoteCaptureCount(snapshot);
  const invited = snapshot.artifacts.filter((a) => a.artifact_type === "rfq_email").length || 3;
  const deadline = formatDeadlineHintForSnapshot(snapshot);
  if (quotes > 0) {
    return {
      kind: "progress",
      title: "Supplier replies received",
      detail: `${quotes} of ${invited} quote${quotes === 1 ? "" : "s"} captured so far. Open the quote tabs in the work panel for details, or ask in the message box for a plain-language summary.${deadline}`,
      footnote:
        "The digital worker reads each reply (including attachment names) and posts a short summary in the thread when triage finishes.",
    };
  }
  return {
    kind: "wait",
    title: "Waiting for replies",
    detail: `${invited} RFQs sent.${deadline || " ~1.5 min from your brief."} Replies are picked up from the sourcing inbox.`,
    footnote: undefined,
  };
}

export function stepGuideShowsWaitingDots(guide: StepGuide, workflowState?: string): boolean {
  if (guide.kind === "progress") return true;
  if (guide.kind === "wait" && workflowState !== "closed") return true;
  return false;
}

function hasRankedSheet(snapshot: InstanceSnapshot): boolean {
  return snapshot.artifacts.some((a) => a.view.type === "sheet" && a.latest_version >= 1);
}

function quoteCaptureCount(snapshot: InstanceSnapshot): number {
  return snapshot.artifacts.filter((a) => a.artifact_type === "quote" && a.latest_version >= 1).length;
}

function proposalCaptureCount(snapshot: InstanceSnapshot): number {
  return snapshot.artifacts.filter((a) => a.artifact_type === "proposal" && a.latest_version >= 1).length;
}

function awaitingProposalsRfpGuide(snapshot: InstanceSnapshot): StepGuide {
  const proposals = proposalCaptureCount(snapshot);
  const invited =
    snapshot.artifacts.filter((a) => a.artifact_type === "rfp_invitation").length ||
    snapshot.artifacts.filter((a) => a.artifact_type === "proposal").length ||
    3;
  const openClarify = snapshot.pending.filter(
    (p) =>
      p.status === "open" &&
      (p.event === "decision.clarification_commercial_approved" ||
        p.event === "decision.clarification_send_approved"),
  );
  if (openClarify.length > 0) {
    return {
      kind: "action",
      title: "Vendor clarifications",
      detail:
        "Commercial questions are for procurement (Noura). Technical questions are for the category manager (Rami). Open the matching card in the thread and the proposal tab for the draft answer.",
    };
  }
  if (proposals >= invited) {
    return {
      kind: "progress",
      title: "Proposals received",
      detail:
        "All vendor proposals are in. The worker will publish commercial, technical, and weighted evaluation sheets; Rami will recommend a vendor for award.",
    };
  }
  return {
    kind: "wait",
    title: "Awaiting vendor proposals",
    detail:
      "Invitations are out. Replies and clarification emails appear under Responses. Commercial clarifications stay with procurement; technical ones with the category manager.",
  };
}

function pendingGuide(snapshot: InstanceSnapshot): StepGuide | null {
  if (specialistAwaitingReply(snapshot)) return null;
  const open = snapshot.pending.filter((p) => p.status === "open");
  const forward = open.filter((p) => p.event !== "task.retry");
  const pending = forward[0] ?? open[0];
  if (!pending) return null;
  if (forward.length === 0) return null;
  const title = pending.title?.trim() || "Your action is needed";
  const detail =
    pending.detail?.trim() ||
    "Use the card in the thread to review and confirm, then continue in the work panel on the right.";
  return { kind: "action", title, detail };
}

export function jobStepGuide(
  snapshot: InstanceSnapshot,
  opts: {
    agentBusy: boolean;
    openPendingForYou: number;
  },
): StepGuide | null {
  const stage = snapshot.stages.find((s) => s.status === "current");
  const stageLabel = stage?.label ?? snapshot.state.replace(/_/g, " ");
  const { agentBusy, openPendingForYou } = opts;
  const awaitingReply = specialistAwaitingReply(snapshot);

  if (openPendingForYou > 0 && !awaitingReply) {
    return pendingGuide(snapshot);
  }

  const cdoWait = masterRfpAwaitingCdoGuide(snapshot, openPendingForYou);
  if (cdoWait) return cdoWait;

  if (snapshot.state === "awaiting_proposals" && snapshot.workflow === "sourcing_rfp" && openPendingForYou === 0) {
    return awaitingProposalsRfpGuide(snapshot);
  }

  if (snapshot.state === "awaiting_quotes" && openPendingForYou === 0) {
    return awaitingQuotesGuide(snapshot);
  }

  if (agentBusy) {
    return {
      kind: "progress",
      title: "Digital worker in progress",
      detail: `Working on ${stageLabel.toLowerCase()}. You can watch the reply above; nothing else is required from you right now.`,
    };
  }

  switch (snapshot.state) {
    case "intake": {
      const brief = snapshot.artifacts.find((a) => a.artifact_type === "brief");
      if (snapshot.intake_ready_for_confirm) {
        const rfpPath =
          snapshot.workflow === "sourcing_rfp"
            ? " After that: shortlist, then a Master RFP document, then CDO approval before invitations."
            : "";
        return {
          kind: "action",
          title: "Confirm the brief",
          detail:
            `The brief in the work panel is ready. Use the Confirm the brief card in the thread above to lock it and continue.${rfpPath}`,
        };
      }
      if (brief && brief.latest_version >= 1 && !awaitingReply) {
        return {
          kind: "action",
          title: "Review your brief",
          detail:
            "Open Documents to check the draft. When Confirm the brief appears in the thread, approve it to continue.",
        };
      }
      if (awaitingReply) {
        return {
          kind: "progress",
          title: "Waiting on your reply",
          detail: "Answer in the chat above. Confirmations appear after you and your specialist finish this exchange.",
        };
      }
      if (agentBusy) {
        return {
          kind: "progress",
          title: "Updating your brief",
          detail: "Your specialist is saving details to the brief. This usually takes less than a minute.",
        };
      }
      return null;
    }
    case "shortlisting": {
      if (awaitingReply) {
        return {
          kind: "progress",
          title: "Waiting on your reply",
          detail: "Answer in the chat above. The ranked list stays in the work panel on the right.",
        };
      }
      const listReady = hasRankedSheet(snapshot);
      if (listReady && snapshot.my_roles.includes("buyer")) {
        const afterShortlist =
          snapshot.workflow === "sourcing_rfp"
            ? " Next: the worker drafts the master RFP; Samir Al-Farsi (CDO) must approve it before invitation emails."
            : " Next: the worker drafts RFQ emails to shortlisted suppliers.";
        return {
          kind: "action",
          title: "Confirm the shortlist",
          detail:
            `Choose at least three rows in the card above the message box, then confirm. The ranked list is also in the work panel on the right.${afterShortlist}`,
        };
      }
      if (listReady) {
        return {
          kind: "wait",
          title: "Ranked list is ready",
          detail:
            "You can review the list on the right. A buyer on your team must claim this job from Team queue and confirm the shortlist before outbound drafts begin.",
        };
      }
      if (snapshot.workflow === "sourcing_rfp") {
        return {
          kind: "progress",
          title: "Building the ranked list",
          detail:
            "The digital worker is ranking options for your brief. After you confirm the shortlist, it will draft the master RFP for CDO approval.",
        };
      }
      return {
        kind: "progress",
        title: "Building the ranked list",
        detail: "The digital worker is ranking options for your brief. It will appear in the work panel when finished.",
      };
    }
    case "master_rfp_drafting": {
      if (snapshot.my_roles.includes("procurement_approver") && cdoMasterRfpReviewOpen(snapshot)) {
        return {
          kind: "action",
          title: "Review the master RFP package",
          detail:
            "Check Documents: RFP validation, template compliance, scoring agreement, and Master RFP. Approve in the thread before invitations.",
        };
      }
      if (cdoMasterRfpReviewOpen(snapshot)) {
        return {
          kind: "wait",
          title: "With the CDO for master RFP approval",
          detail:
            "Samir reviews validation, agreed scoring, and Master RFP. Vendor invitations start after approval.",
        };
      }
      return {
        kind: "progress",
        title: "Specification and Master RFP",
        detail:
          "Procurement validates BoQ, terms, and fixed-price scope; requester may upload sections. Lock scoring method, then draft Master RFP for CDO.",
      };
    }
    case "rfp_invitation_drafting":
      return {
        kind: "progress",
        title: "Vendor invitation emails",
        detail:
          "The master RFP is approved. The worker is drafting one invitation per shortlisted vendor, each including the RFP document.",
      };
    case "rfp_sending": {
      const rfpDrafts = messageComposerArtifacts(snapshot.artifacts).length;
      if (rfpDrafts > 0) {
        return {
          kind: "action",
          title: "Review and send invitations",
          detail:
            "Open each invitation in the work panel, confirm the RFP is attached, then use Approve and send.",
        };
      }
      return {
        kind: "progress",
        title: "Preparing invitations to send",
        detail: "Drafts will appear here when the worker finishes.",
      };
    }
    case "awaiting_proposals":
      return awaitingQuotesGuide(snapshot);
    case "rfq_drafting":
      return {
        kind: "progress",
        title: "Outbound drafts in progress",
        detail:
          "The worker is writing one message per shortlisted row. Review the drafts in the panel on the right when they appear.",
      };
    case "rfq_sending": {
      const drafts = messageComposerArtifacts(snapshot.artifacts).length;
      if (drafts > 0 && !awaitingReply) {
        return {
          kind: "action",
          title: "Review and send",
          detail:
            "Draft messages are ready in the work panel. Open each tab, check the text, then use Approve and send below.",
        };
      }
      return {
        kind: "progress",
        title: "Preparing to send",
        detail: "The worker is finishing drafts. Sending will open here when the messages are ready.",
      };
    }
    case "awaiting_quotes":
      return awaitingQuotesGuide(snapshot);
    case "bafo":
      return {
        kind: "action",
        title: "BAFO — module pricing",
        detail:
          "Open Module comparison and Module scores, then each BAFO draft under Drafts. Challenge outlier module prices (why X when fair looks Y vs peers). Approve Send BAFO cards in the thread; finish with Complete BAFO round.",
      };
    case "comparison": {
      if (snapshot.workflow === "sourcing_rfp") {
        return {
          kind: "action",
          title: "Recommend vendor for award",
          detail:
            "After BAFO, review Commercial eval, Technical eval, and Weighted eval. Rami uses Recommend vendor for award — pick a row or note a different vendor.",
        };
      }
      const quoteHint = "Open the Quote tab in the work panel — the inbound email excerpt is at the top";
      return {
        kind: "action",
        title: "Award the order",
        detail: `${quoteHint}, then use Award this order in the thread.`,
      };
    }
    case "ordering": {
      const orderingRetry = snapshot.pending.some(
        (p) =>
          p.status === "open" &&
          p.event === "task.retry" &&
          /ordering/i.test(p.title),
      );
      if (orderingRetry) {
        return {
          kind: "wait",
          title: "Ordering paused",
          detail:
            "The requisition step failed before a draft was saved. In the thread, use Retry: Requisition (signed in as the buyer).",
        };
      }
      return {
        kind: "progress",
        title: "Requisition in progress",
        detail:
          "The worker is preparing the Fusion requisition. After AOS approvals, Oracle Fusion converts it to a PO.",
      };
    }
    case "closed":
      return {
        kind: "complete",
        title: "Requisition submitted",
        detail:
          "The purchase requisition was sent to Oracle Fusion. Open Requisition in the work panel; Fusion handles PO conversion.",
      };
    case "conversation":
    case "chat": {
      const personTurns = snapshot.turns.filter((t) => t.author.kind === "person").length;
      const seatReplies = snapshot.turns.filter((t) => t.author.kind === "seat").length;
      if (personTurns >= 1 && seatReplies >= 1 && !awaitingReply) {
        return {
          kind: "progress",
          title: "Starting your brief",
          detail: "Intake is opening — the draft request will appear in the work panel shortly.",
        };
      }
      if (agentBusy) {
        return {
          kind: "progress",
          title: "Digital worker in progress",
          detail: "Your specialist is reading your message. The work panel fills in once intake starts.",
        };
      }
      return null;
    }
    default:
      return {
        kind: "wait",
        title: stageLabel,
        detail: "Follow the thread and work panel for this stage.",
      };
  }
}
