import type { components } from "../../api/schema";
import type { InstanceSnapshot } from "./jobStreamReducer";

type PendingItem = components["schemas"]["PendingItem"];

/** Open decision items not already embedded in a turn. */
export function orphanOpenDecisions(snapshot: InstanceSnapshot): PendingItem[] {
  const pendingInTurns = new Set<string>();
  for (const turn of snapshot.turns) {
    for (const block of turn.blocks ?? []) {
      if (block.kind === "pending_ref" && "pending_id" in block) pendingInTurns.add(block.pending_id);
    }
  }
  return snapshot.pending.filter(
    (p) => p.status === "open" && p.kind === "decision" && !pendingInTurns.has(p.pending_id),
  );
}

function currentStageLabel(snapshot: InstanceSnapshot): string {
  const current = snapshot.stages.find((s) => s.status === "current");
  return (current?.label ?? snapshot.state.replace(/_/g, " ")).trim();
}

export function isRetryPending(pending: PendingItem): boolean {
  return pending.event === "task.retry";
}

export function isForwardDecision(pending: PendingItem): boolean {
  return pending.kind === "decision" && pending.event !== "task.retry";
}

/** Whether a task.retry pending item belongs to the stage the job is in now. */
export function retryMatchesCurrentStage(retry: PendingItem, snapshot: InstanceSnapshot): boolean {
  if (retry.event !== "task.retry") return false;
  const label = currentStageLabel(snapshot).toLowerCase();
  const title = retry.title.toLowerCase();
  const stateWords = snapshot.state.replace(/_/g, " ").toLowerCase();
  return title.includes(label) || title.includes(stateWords);
}

export type ConversationPendingSplit = {
  /** Cards to show prominently (one forward decision, or at most one retry for this stage). */
  primary: PendingItem[];
  /** Older retries — optional collapsible list. */
  staleRetries: PendingItem[];
};

export function splitConversationPending(
  orphan: PendingItem[],
  snapshot: InstanceSnapshot,
): ConversationPendingSplit {
  const forward = orphan.filter((p) => p.event !== "task.retry");
  const retries = orphan.filter((p) => p.event === "task.retry");

  if (forward.length > 0) {
    return { primary: forward, staleRetries: retries };
  }

  const current = retries.filter((r) => retryMatchesCurrentStage(r, snapshot));
  const stale = retries.filter((r) => !retryMatchesCurrentStage(r, snapshot));
  const sortedCurrent = [...current].sort((a, b) => b.created_at.localeCompare(a.created_at));
  const primary = sortedCurrent.length > 0 ? [sortedCurrent[0]] : [];
  const staleRetries = [...stale, ...sortedCurrent.slice(1)];
  return { primary, staleRetries };
}
