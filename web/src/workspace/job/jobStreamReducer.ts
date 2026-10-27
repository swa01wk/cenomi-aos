import type { components } from "../../api/schema";
import type { MessageDelta, ToolActivity, Turn } from "../../components/types";
import type { UiEvent } from "../../api/stream";
import { isDeltaEventType, parseStreamSeq } from "../../api/eventSeq";

export type InstanceSnapshot = components["schemas"]["InstanceSnapshot"];

export type JobStreamSideEffect =
  | { kind: "refetch_snapshot" }
  | { kind: "invalidate_artifact"; artifactId: string; version: number }
  | { kind: "invalidate_documents" };

export type JobStreamAuxState = {
  deltas: MessageDelta[];
  toolActivityByAttempt: Map<string, ToolActivity>;
  lastDeltaSeqByTurn: Map<string, number>;
  lastAppliedStreamSeq: number;
  seenEventIds: Set<string>;
};

export function emptyJobStreamAux(lastCursor?: string): JobStreamAuxState {
  const seq = lastCursor ? parseStreamSeq(lastCursor) : null;
  return {
    deltas: [],
    toolActivityByAttempt: new Map(),
    lastDeltaSeqByTurn: new Map(),
    lastAppliedStreamSeq: seq ?? -1,
    seenEventIds: new Set(),
  };
}

export function markStages(stages: InstanceSnapshot["stages"], toState: string): InstanceSnapshot["stages"] {
  let seenCurrent = false;
  return stages.map((s) => {
    if (s.state === toState) {
      seenCurrent = true;
      return { ...s, status: "current" as const };
    }
    if (!seenCurrent) return { ...s, status: "done" as const };
    return { ...s, status: "next" as const };
  });
}

function upsertTurn(turns: Turn[], turn: Turn): Turn[] {
  const i = turns.findIndex((t) => t.turn_id === turn.turn_id);
  if (i < 0) return [...turns, turn].sort((a, b) => a.seq - b.seq);
  const next = [...turns];
  next[i] = turn;
  return next.sort((a, b) => a.seq - b.seq);
}

function clearDeltasForTurn(aux: JobStreamAuxState, turnId: string): void {
  aux.deltas = aux.deltas.filter((d) => d.turn_id !== turnId);
  aux.lastDeltaSeqByTurn.delete(turnId);
}

function clearToolActivityForAttempt(aux: JobStreamAuxState, attemptId: string): void {
  aux.toolActivityByAttempt.delete(attemptId);
}

export type ReduceJobStreamResult = {
  snapshot: InstanceSnapshot;
  aux: JobStreamAuxState;
  effects: JobStreamSideEffect[];
  skip: boolean;
};

export function reduceJobStreamEvent(
  snapshot: InstanceSnapshot,
  aux: JobStreamAuxState,
  event: UiEvent,
): ReduceJobStreamResult {
  const effects: JobStreamSideEffect[] = [];

  if (isDeltaEventType(event.type)) {
    const data = event.data as MessageDelta;
    const last = aux.lastDeltaSeqByTurn.get(data.turn_id) ?? -1;
    if (data.seq <= last) {
      return { snapshot, aux, effects, skip: true };
    }
    aux.lastDeltaSeqByTurn.set(data.turn_id, data.seq);
    aux.deltas = [...aux.deltas, data];
    return { snapshot, aux, effects, skip: false };
  }

  const seq = parseStreamSeq(event.id);
  if (seq != null) {
    if (seq <= aux.lastAppliedStreamSeq || aux.seenEventIds.has(event.id)) {
      return { snapshot, aux, effects, skip: true };
    }
    aux.lastAppliedStreamSeq = seq;
    aux.seenEventIds.add(event.id);
  }

  let next = snapshot;

  switch (event.type) {
    case "snapshot.required":
      effects.push({ kind: "refetch_snapshot" });
      break;
    case "instance.state_changed": {
      const data = event.data as {
        to: string;
        version: number;
      };
      next = {
        ...next,
        state: data.to,
        version: data.version,
        stages: markStages(next.stages, data.to),
      };
      break;
    }
    case "turn.created":
    case "agent.message.completed": {
      const data = event.data as { turn: Turn };
      next = { ...next, turns: upsertTurn(next.turns, data.turn) };
      clearDeltasForTurn(aux, data.turn.turn_id);
      if (event.type === "agent.message.completed") {
        // Deltas are keyed by the turn being answered, not the reply's own id; the completed reply replaces them.
        // Only this viewer's own reply streams to them, one at a time, so all live text belongs to it.
        aux.deltas = [];
        aux.lastDeltaSeqByTurn.clear();
      }
      if (data.turn.attempt_id) clearToolActivityForAttempt(aux, data.turn.attempt_id);
      break;
    }
    case "agent.tool.activity": {
      const data = event.data as ToolActivity;
      aux.toolActivityByAttempt.set(data.attempt_id, data);
      break;
    }
    case "artifact.version_created": {
      const data = event.data as {
        artifact_id: string;
        version: number;
        status: InstanceSnapshot["artifacts"][0]["status"];
        by: string;
      };
      effects.push({ kind: "invalidate_artifact", artifactId: data.artifact_id, version: data.version });
      if (!next.artifacts.some((a) => a.artifact_id === data.artifact_id)) {
        // A new artifact: the event has no name or view, so take them from a fresh snapshot.
        effects.push({ kind: "refetch_snapshot" });
        break;
      }
      next = {
        ...next,
        artifacts: next.artifacts.map((a) =>
          a.artifact_id === data.artifact_id
            ? {
                ...a,
                latest_version: data.version,
                status: data.status,
                versions: (a.versions ?? []).some((v) => v.version === data.version)
                  ? (a.versions ?? [])
                  : [...(a.versions ?? []), { version: data.version, by: data.by, at: event.at }],
              }
            : a,
        ),
      };
      break;
    }
    case "participant.bound":
      // A new role can reveal columns that were hidden. Reload the documents.
      effects.push({ kind: "refetch_snapshot" });
      effects.push({ kind: "invalidate_documents" });
      break;
    case "pending.created": {
      const data = event.data as { pending: InstanceSnapshot["pending"][0] };
      next = {
        ...next,
        pending: [...next.pending.filter((p) => p.pending_id !== data.pending.pending_id), data.pending],
      };
      break;
    }
    case "pending.resolved": {
      const data = event.data as { pending_id: string };
      next = {
        ...next,
        pending: next.pending.filter((p) => p.pending_id !== data.pending_id),
      };
      break;
    }
    case "kill_switch.changed":
      effects.push({ kind: "refetch_snapshot" });
      break;
    default:
      break;
  }

  return { snapshot: next, aux, effects, skip: false };
}
