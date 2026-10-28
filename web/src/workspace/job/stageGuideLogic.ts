import type { InstanceSnapshot } from "./jobStreamReducer";
import { messageComposerArtifacts } from "./workComposerHint";

export type StepGuide = {
  kind: "action" | "wait" | "progress" | "complete";
  title: string;
  detail: string;
  footnote?: string;
};

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
  return guide;
}

export function stageGuideIsLive(guide: StepGuide, _workflowState: string): boolean {
  return guide.kind === "progress";
}

export function stepGuideShowsWaitingDots(guide: StepGuide, workflowState?: string): boolean {
  if (guide.kind === "progress") return true;
  if (guide.kind === "wait" && workflowState !== "closed") return true;
  return false;
}

function viewerIsBuyer(snapshot: InstanceSnapshot): boolean {
  return snapshot.my_roles.includes("buyer");
}

function hasSupplierList(snapshot: InstanceSnapshot): boolean {
  return snapshot.artifacts.some((a) => a.artifact_type === "supplier_list" && a.latest_version >= 1);
}

export function jobStepGuide(
  snapshot: InstanceSnapshot,
  opts: {
    agentBusy: boolean;
    openPendingForYou: number;
  },
): StepGuide | null {
  const stage = snapshot.stages.find((s) => s.status === "current");
  const stageLabel = stage?.label ?? snapshot.state;
  const { agentBusy, openPendingForYou } = opts;

  if (openPendingForYou > 0) {
    const open = snapshot.pending.filter((p) => p.status === "open");
    const forward = open.filter((p) => p.event !== "task.retry");
    const pending = forward[0] ?? open[0];
    if (pending?.event === "decision.shortlist_confirmed") {
      return {
        kind: "action",
        title: "Pick suppliers to invite",
        detail:
          "Select at least three suppliers in the card in the thread. You can edit the note, then confirm the shortlist.",
      };
    }
    if (pending?.event === "decision.supplier_selected") {
      return {
        kind: "action",
        title: "Choose a supplier",
        detail:
          "Review the comparison on the right, select a supplier in the card in the thread, then confirm your choice.",
      };
    }
    if (forward.length > 0) {
      return null;
    }
    return null;
  }

  if (agentBusy) {
    return {
      kind: "progress",
      title: "Digital worker in progress",
      detail: `Working on ${stageLabel.toLowerCase()}. You can watch the reply above; nothing else is required from you right now.`,
    };
  }

  switch (snapshot.state) {
    case "intake":
      return {
        kind: "progress",
        title: "Confirm the request",
        detail:
          "The worker is shaping your brief. When the brief is ready, you will confirm it here so sourcing can start.",
      };
    case "shortlisting": {
      const listReady = hasSupplierList(snapshot);
      if (listReady && viewerIsBuyer(snapshot)) {
        return {
          kind: "action",
          title: "Pick suppliers to invite",
          detail:
            "Choose at least three suppliers in the card above the message box, then confirm the shortlist. The ranked list is also in the work panel on the right.",
        };
      }
      if (listReady) {
        return {
          kind: "wait",
          title: "Supplier list is ready",
          detail:
            "You can review the ranked list on the right. A sourcing buyer must claim this job from Team queue and pick at least three suppliers before RFQ emails can be drafted.",
          footnote: "Sign in as Noura (sourcing), open Team queue, claim this job, then confirm the shortlist.",
        };
      }
      return {
        kind: "progress",
        title: "Suppliers being ranked",
        detail:
          "The digital worker is building a supplier list. It will appear in the work panel when ranking finishes.",
      };
    }
    case "rfq_drafting":
      return {
        kind: "progress",
        title: "RFQ emails being drafted",
        detail:
          "The worker is writing one email per shortlisted supplier. Review the drafts in the panel on the right when they appear.",
      };
    case "rfq_sending": {
      const drafts = messageComposerArtifacts(snapshot.artifacts).length;
      if (drafts > 0) {
        return {
          kind: "action",
          title: "Review and send RFQs",
          detail:
            "Draft emails are ready in the work panel. Open each tab, check the text, then use Approve and send to suppliers.",
        };
      }
      return {
        kind: "progress",
        title: "Preparing to send",
        detail: "The worker is finishing RFQ drafts. Sending will open here when the emails are ready.",
      };
    }
    case "awaiting_quotes": {
      const quotes = snapshot.artifacts.filter((a) => a.artifact_type === "quote").length;
      const invited = quotes > 0 ? quotes : messageComposerArtifacts(snapshot.artifacts).length || 3;
      return {
        kind: "wait",
        title: "Waiting for supplier quotes",
        detail:
          quotes > 0
            ? `${quotes} quote${quotes === 1 ? "" : "s"} recorded so far. The digital worker adds each reply as it arrives and will move to comparison when enough quotes are in.`
            : `RFQs are with your suppliers (${invited} invited). The digital worker watches for replies; you do not need to refresh or send again.`,
        footnote:
          quotes > 0
            ? "Each quote tab shows what we captured from the supplier reply. Ask in the message box below (for example, who has replied?)."
            : "Replies must reach the mock mail listener (Gmail alone is not read). Ask in the message box below. Comparison opens when the workflow rules are satisfied.",
      };
    }
    case "comparison":
      return {
        kind: "action",
        title: "Compare quotes",
        detail:
          "Quotes are in the work panel. Review the comparison and confirm your supplier choice when you are ready.",
      };
    case "ordering":
      return {
        kind: "progress",
        title: "Purchase order in progress",
        detail: "The worker is preparing the PO. An approver may need to sign off before it is sent.",
      };
    case "closed":
      return {
        kind: "complete",
        title: "Lifecycle complete",
        detail: "Nothing else is required on this job. Use the work panel for final documents.",
      };
    default:
      return {
        kind: "progress",
        title: stageLabel,
        detail: "The job is moving through the workflow. Updates appear in the conversation and work panel.",
      };
  }
}
