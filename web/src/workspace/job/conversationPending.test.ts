import { describe, expect, it } from "vitest";
import type { InstanceSnapshot } from "./jobStreamReducer";
import { TEST_SNAPSHOT_SHELL, TEST_WORKFLOW } from "../testJobFixtures";
import { retryMatchesCurrentStage, splitConversationPending } from "./conversationPending";

function snap(partial: Partial<InstanceSnapshot> & Pick<InstanceSnapshot, "pending">): InstanceSnapshot {
  const { pending, ...rest } = partial;
  return {
    ...TEST_SNAPSHOT_SHELL,
    instance_id: "QQ-1",
    workflow: TEST_WORKFLOW,
    title: "Test",
    state: "comparison",
    stages: [{ state: "comparison", label: "Comparison", status: "current" }],
    turns: [],
    artifacts: [],
    my_roles: ["buyer"],
    ...rest,
    pending,
  } as InstanceSnapshot;
}

describe("splitConversationPending", () => {
  it("shows forward decisions and tucks all retries under stale", () => {
    const pending = [
      {
        pending_id: "p1",
        instance_id: "QQ-1",
        kind: "decision" as const,
        event: "decision.party_selected",
        title: "Select the winning row",
        for_role: "buyer",
        status: "open" as const,
        created_at: "2026-10-28T08:00:00Z",
      },
      {
        pending_id: "p2",
        instance_id: "QQ-1",
        kind: "decision" as const,
        event: "task.retry",
        title: "Retry: Awaiting replies",
        for_role: "buyer",
        status: "open" as const,
        created_at: "2026-10-28T07:00:00Z",
      },
      {
        pending_id: "p3",
        instance_id: "QQ-1",
        kind: "decision" as const,
        event: "task.retry",
        title: "Retry: Comparison",
        for_role: "buyer",
        status: "open" as const,
        created_at: "2026-10-28T07:30:00Z",
      },
    ];
    const { primary, staleRetries } = splitConversationPending(pending, snap({ pending }));
    expect(primary.map((p) => p.pending_id)).toEqual(["p1"]);
    expect(staleRetries.map((p) => p.pending_id)).toEqual(["p2", "p3"]);
  });

  it("holds decision cards while the specialist awaits a user reply", () => {
    const pending = [
      {
        pending_id: "p-brief",
        instance_id: "QQ-1",
        kind: "decision" as const,
        event: "decision.brief_confirmed",
        title: "Confirm the brief",
        for_role: "requester",
        status: "open" as const,
        created_at: "2026-10-28T08:00:00Z",
      },
    ];
    const snapshot = snap({
      pending,
      state: "intake",
      turns: [
        {
          turn_id: "t-seat",
          seq: 2,
          at: "2026-10-29T12:00:00Z",
          author: { kind: "seat", id: "seat_sourcing_poc", name: "Noor" },
          blocks: [{ kind: "text", text: "Which site?" }],
        },
      ],
    });
    const { primary } = splitConversationPending(pending, snapshot);
    expect(primary).toHaveLength(0);
  });

  it("hides brief confirm when the specialist spoke again after the card opened", () => {
    const pending = [
      {
        pending_id: "p-brief",
        instance_id: "QQ-1",
        kind: "decision" as const,
        event: "decision.brief_confirmed",
        title: "Confirm the brief",
        for_role: "requester",
        status: "open" as const,
        created_at: "2026-11-02T06:50:00Z",
      },
    ];
    const snapshot = snap({
      pending,
      state: "intake",
      turns: [
        {
          turn_id: "t-person",
          seq: 1,
          at: "2026-11-02T06:51:00Z",
          author: { kind: "person", id: "faisal", name: "Faisal" },
          blocks: [{ kind: "text", text: "10 iphones" }],
        },
        {
          turn_id: "t-seat",
          seq: 2,
          at: "2026-11-02T06:52:00Z",
          author: { kind: "seat", id: "seat_sourcing_poc", name: "Noor" },
          blocks: [{ kind: "text", text: "Who signs off on quality?" }],
        },
      ],
    });
    const { primary } = splitConversationPending(pending, snapshot);
    expect(primary).toHaveLength(0);
  });

  it("shows only the current-stage retry when no forward decision", () => {
    const pending = [
      {
        pending_id: "p2",
        instance_id: "QQ-1",
        kind: "decision" as const,
        event: "task.retry",
        title: "Retry: Awaiting replies",
        for_role: "buyer",
        status: "open" as const,
        created_at: "2026-10-28T07:00:00Z",
      },
      {
        pending_id: "p3",
        instance_id: "QQ-1",
        kind: "decision" as const,
        event: "task.retry",
        title: "Retry: Comparison",
        for_role: "buyer",
        status: "open" as const,
        created_at: "2026-10-28T07:30:00Z",
      },
    ];
    const { primary, staleRetries } = splitConversationPending(pending, snap({ pending }));
    expect(primary.map((p) => p.pending_id)).toEqual(["p3"]);
    expect(staleRetries.map((p) => p.pending_id)).toEqual(["p2"]);
  });
});

describe("retryMatchesCurrentStage", () => {
  it("matches comparison retry on comparison stage", () => {
    const retry = {
      pending_id: "p",
      instance_id: "QQ-1",
      kind: "decision" as const,
      event: "task.retry",
      title: "Retry: Comparison",
      for_role: "buyer",
      status: "open" as const,
      created_at: "2026-10-28T08:00:00Z",
    };
    expect(retryMatchesCurrentStage(retry, snap({ pending: [retry] }))).toBe(true);
  });
});
