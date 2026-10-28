import { describe, expect, it } from "vitest";
import type { InstanceSnapshot } from "./jobStreamReducer";
import { composerBlockedForPoLoop } from "./composerGate";

function snap(partial: Partial<InstanceSnapshot>): InstanceSnapshot {
  return {
    instance_id: "QQ-1",
    title: "Test",
    workflow: "quick_quote",
    pack_version: "p@1",
    version: 1,
    state: "ordering",
    stages: [],
    participants: [],
    my_roles: ["buyer"],
    pending: [],
    artifacts: [],
    turns: [],
    cursor: "0",
    ...partial,
  } as InstanceSnapshot;
}

describe("composerBlockedForPoLoop", () => {
  it("blocks after repeated PO Q&A in ordering", () => {
    const msg = composerBlockedForPoLoop(
      snap({
        turns: [
          { turn_id: "1", seq: 1, at: "2026-10-28T08:00:00Z", author: { kind: "person", id: "n", name: "N" }, blocks: [{ kind: "text", text: "a" }] },
          { turn_id: "2", seq: 2, at: "2026-10-28T08:01:00Z", author: { kind: "seat", id: "s", name: "Agent" }, blocks: [{ kind: "text", text: "q?" }] },
          { turn_id: "3", seq: 3, at: "2026-10-28T08:02:00Z", author: { kind: "person", id: "n", name: "N" }, blocks: [{ kind: "text", text: "b" }] },
          { turn_id: "4", seq: 4, at: "2026-10-28T08:03:00Z", author: { kind: "seat", id: "s", name: "Agent" }, blocks: [{ kind: "text", text: "q again?" }] },
        ],
      }),
    );
    expect(msg).toMatch(/repeat the same questions/);
  });

  it("does not block closed jobs", () => {
    expect(composerBlockedForPoLoop(snap({ state: "closed" }))).toBeUndefined();
  });
});
