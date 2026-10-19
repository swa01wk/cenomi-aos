import { describe, expect, it } from "vitest";
import type { InstanceSnapshot } from "./jobStreamReducer";
import { emptyJobStreamAux, markStages, reduceJobStreamEvent } from "./jobStreamReducer";

function baseSnapshot(): InstanceSnapshot {
  return {
    instance_id: "inst-1",
    title: "Job",
    workflow: "wf",
    pack_version: "p@1",
    state: "s1",
    version: 1,
    stages: [
      { state: "s1", label: "One", status: "current" },
      { state: "s2", label: "Two", status: "next" },
    ],
    participants: [],
    my_roles: ["requester"],
    pending: [],
    artifacts: [],
    turns: [],
    cursor: "instance:inst-1:0",
  };
}

describe("markStages", () => {
  it("marks done, current and next from target state", () => {
    const stages = markStages(baseSnapshot().stages, "s2");
    expect(stages[0]?.status).toBe("done");
    expect(stages[1]?.status).toBe("current");
  });
});

describe("reduceJobStreamEvent", () => {
  it("dedupes by stream seq", () => {
    const snap = baseSnapshot();
    const aux = emptyJobStreamAux("instance:inst-1:0");
    const ev = {
      id: "instance:inst-1:1",
      type: "instance.state_changed",
      at: "t",
      data: { to: "s2", version: 2 },
    };
    const first = reduceJobStreamEvent(snap, aux, ev);
    expect(first.skip).toBe(false);
    const second = reduceJobStreamEvent(first.snapshot, first.aux, ev);
    expect(second.skip).toBe(true);
  });

  it("appends deltas and ignores stale seq", () => {
    const aux = emptyJobStreamAux();
    const d1 = {
      id: "ephemeral",
      type: "agent.message.delta",
      at: "t",
      data: { instance_id: "inst-1", turn_id: "t1", seq: 1, text: "A" },
    };
    const r1 = reduceJobStreamEvent(baseSnapshot(), aux, d1);
    expect(r1.aux.deltas).toHaveLength(1);

    const d0 = {
      id: "ephemeral2",
      type: "agent.message.delta",
      at: "t",
      data: { instance_id: "inst-1", turn_id: "t1", seq: 0, text: "Z" },
    };
    const r2 = reduceJobStreamEvent(r1.snapshot, r1.aux, d0);
    expect(r2.skip).toBe(true);
    expect(r2.aux.deltas).toHaveLength(1);
  });

  it("clears tool activity when a turn completes for that attempt", () => {
    let aux = emptyJobStreamAux("instance:inst-1:5");
    const toolEv = {
      id: "instance:inst-1:6",
      type: "agent.tool.activity",
      at: "t",
      data: {
        instance_id: "inst-1",
        attempt_id: "att-1",
        tool: "browse",
        label: "Looking",
        state: "allowed",
      },
    };
    let r = reduceJobStreamEvent(baseSnapshot(), aux, toolEv);
    expect(r.aux.toolActivityByAttempt.get("att-1")?.label).toBe("Looking");

    const done = {
      id: "instance:inst-1:7",
      type: "agent.message.completed",
      at: "t",
      data: {
        instance_id: "inst-1",
        turn: {
          turn_id: "turn-1",
          seq: 2,
          author: { kind: "seat" as const, id: "s", name: "Agent" },
          blocks: [{ kind: "text" as const, text: "Done" }],
          at: "t",
          attempt_id: "att-1",
        },
      },
    };
    r = reduceJobStreamEvent(r.snapshot, r.aux, done);
    expect(r.aux.toolActivityByAttempt.has("att-1")).toBe(false);
    expect(r.aux.deltas).toHaveLength(0);
  });

  it("requests snapshot refetch on snapshot.required", () => {
    const aux = emptyJobStreamAux("instance:inst-1:3");
    const r = reduceJobStreamEvent(baseSnapshot(), aux, {
      id: "instance:inst-1:4",
      type: "snapshot.required",
      at: "t",
      data: { reason: "gap" },
    });
    expect(r.effects).toEqual([{ kind: "refetch_snapshot" }]);
  });
});
