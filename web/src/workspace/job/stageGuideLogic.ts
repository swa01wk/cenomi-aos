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

function hasRankedSheet(snapshot: InstanceSnapshot): boolean {
  return snapshot.artifacts.some((a) => a.view.type === "sheet" && a.latest_version >= 1);
}

function inboundReplyCount(snapshot: InstanceSnapshot): number {
  return snapshot.artifacts.filter((a) => a.view.type === "tracker" && a.latest_version >= 1).length;
}

function pendingGuide(snapshot: InstanceSnapshot): StepGuide | null {
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

  if (openPendingForYou > 0) {
    return pendingGuide(snapshot);
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
          "The worker is shaping your brief. When the brief is ready, you will confirm it here so the next stage can start.",
      };
    case "shortlisting": {
      const listReady = hasRankedSheet(snapshot);
      if (listReady && snapshot.my_roles.includes("buyer")) {
        return {
          kind: "action",
          title: "Confirm the shortlist",
          detail:
            "Choose at least three rows in the card above the message box, then confirm. The ranked list is also in the work panel on the right.",
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
      return {
        kind: "progress",
        title: "Building the ranked list",
        detail: "The digital worker is ranking options for your brief. It will appear in the work panel when finished.",
      };
    }
    case "rfq_drafting":
      return {
        kind: "progress",
        title: "Outbound drafts in progress",
        detail:
          "The worker is writing one message per shortlisted row. Review the drafts in the panel on the right when they appear.",
      };
    case "rfq_sending": {
      const drafts = messageComposerArtifacts(snapshot.artifacts).length;
      if (drafts > 0) {
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
    case "awaiting_quotes": {
      const replies = inboundReplyCount(snapshot);
      const invited = replies > 0 ? replies : messageComposerArtifacts(snapshot.artifacts).length || 3;
      return {
        kind: "wait",
        title: "Waiting for replies",
        detail:
          replies > 0
            ? `${replies} inbound record${replies === 1 ? "" : "s"} so far. The digital worker adds each reply as it arrives and will move on when enough responses are in.`
            : `Messages were sent (${invited} parties). The digital worker watches for replies; you do not need to refresh or send again.`,
        footnote:
          replies > 0
            ? "Each tracker tab shows what we captured from the reply. Ask in the message box below (for example, who has replied?)."
            : "Replies must reach the configured mail listener. Ask in the message box below. Comparison opens when the workflow rules are satisfied.",
      };
    }
    case "comparison":
      return {
        kind: "action",
        title: "Review the comparison",
        detail:
          "Results are in the work panel. Review the comparison and confirm your choice in the thread when you are ready.",
      };
    case "ordering":
      return {
        kind: "progress",
        title: "Purchase order in progress",
        detail: "The worker is preparing the order record. An approver may need to sign off before it is sent.",
      };
    case "closed":
      return {
        kind: "complete",
        title: "Lifecycle complete",
        detail: "Nothing else is required on this job. Use the work panel for final documents.",
      };
    default:
      return {
        kind: "wait",
        title: stageLabel,
        detail: "Follow the thread and work panel for this stage.",
      };
  }
}
