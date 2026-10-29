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
