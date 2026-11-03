import type { components } from "../../api/schema";
import type { InstanceSnapshot } from "./jobStreamReducer";
import { isCoordinatorJob } from "../workspaceEntry";

type Turn = components["schemas"]["Turn"];
type PendingItem = components["schemas"]["PendingItem"];

/** Specialist sent the last message and is waiting on the user — defer confirm cards and stage nudges. */
export function specialistAwaitingReply(snapshot: InstanceSnapshot): boolean {
  const last = snapshot.turns.at(-1);
  return last != null && last.author.kind !== "person";
}

/** Brief confirm only after the requester has replied to the latest specialist message. */
export function holdBriefConfirmDecision(snapshot: InstanceSnapshot, pending: PendingItem): boolean {
  if (pending.event !== "decision.brief_confirmed" || snapshot.state !== "intake") {
    return false;
  }
  if (snapshot.intake_ready_for_confirm) {
    return false;
  }
  if (specialistAwaitingReply(snapshot)) {
    return true;
  }
  const opened = Date.parse(pending.created_at);
  if (Number.isNaN(opened)) {
    return false;
  }
  const lastSeat = [...snapshot.turns].reverse().find((t) => t.author.kind === "seat");
  if (lastSeat && Date.parse(lastSeat.at) > opened) {
    return true;
  }
  return false;
}

export function briefArtifact(snapshot: InstanceSnapshot) {
  return snapshot.artifacts.find((a) => a.artifact_type === "brief" && a.latest_version >= 1);
}

function requesterPersonId(snapshot: InstanceSnapshot): string | undefined {
  return snapshot.participants.find((p) => p.role === "requester")?.person_id;
}

function viewerIsRequester(snapshot: InstanceSnapshot): boolean {
  return snapshot.my_roles.includes("requester");
}

/** First brief version timestamp — intake chat before this is collapsed for buyers. */
function briefV1At(snapshot: InstanceSnapshot): string | undefined {
  const brief = briefArtifact(snapshot);
  if (!brief?.versions?.length) return undefined;
  const first = brief.versions.find((v) => v.version === 1) ?? brief.versions.at(-1);
  return first?.at;
}

/**
 * Specialist chat visibility:
 * - Requester: hide pre-brief intake clutter; keep latest person line (handoff seed).
 * - Buyer / others: hide the requester's thread (brief summary covers need); hide pre-brief seat intake chatter.
 */
export function specialistChatTurns(snapshot: InstanceSnapshot, turns: Turn[]): Turn[] {
  if (snapshot.workflow === "workspace_coordination" || isCoordinatorJob(snapshot)) {
    return turns;
  }

  const requesterId = requesterPersonId(snapshot);
  if (!viewerIsRequester(snapshot) && requesterId) {
    const cutoff = briefV1At(snapshot);
    return turns.filter((t) => {
      if (t.author.kind === "person" && t.author.id === requesterId) {
        return false;
      }
      if (cutoff && t.author.kind === "seat" && t.at < cutoff) {
        return false;
      }
      return true;
    });
  }

  const brief = briefArtifact(snapshot);
  if (!brief?.versions?.length) {
    return turns;
  }
  const cutoff = briefV1At(snapshot);
  if (!cutoff) {
    return turns;
  }
  const personTurns = turns.filter((t) => t.author.kind === "person");
  const latestPersonId = personTurns.at(-1)?.turn_id;
  return turns.filter((t) => {
    if (t.author.kind !== "person") return true;
    if (latestPersonId && t.turn_id === latestPersonId) return true;
    return t.at > cutoff;
  });
}

export function showBriefSummaryInChat(snapshot: InstanceSnapshot): boolean {
  if (snapshot.workflow === "workspace_coordination" || isCoordinatorJob(snapshot)) {
    return false;
  }
  return Boolean(briefArtifact(snapshot));
}
