import type { InstanceSnapshot } from "./jobStreamReducer";

/** Block chat when it would re-trigger a stuck PO question loop (answers belong in artifacts / approvals). */
export function composerBlockedForPoLoop(snapshot: InstanceSnapshot): string | undefined {
  if (snapshot.state !== "ordering") return undefined;
  const openRetry = snapshot.pending.some((p) => p.status === "open" && p.event === "task.retry");
  const personTurns = snapshot.turns.filter((t) => t.author.kind === "person").length;
  const agentBlocks = snapshot.turns.flatMap((t) =>
    t.author.kind === "seat" ? (t.blocks ?? []).filter((b) => b.kind === "text") : [],
  ).length;
  if (personTurns >= 2 && agentBlocks >= 2 && !openRetry) {
    return "The PO step is waiting on the digital worker or approvals. Sending more messages can repeat the same questions. Use Optional retry below or refresh in a moment.";
  }
  return undefined;
}
