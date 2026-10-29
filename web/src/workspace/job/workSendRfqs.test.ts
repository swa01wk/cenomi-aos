import { describe, expect, it } from "vitest";
import type { InstanceSnapshot } from "./jobStreamReducer";
import { TEST_SNAPSHOT_SHELL, TEST_WORKFLOW } from "../testJobFixtures";
import { hasOpenTaskRetry, showSendRfqsBar } from "./workSendRfqs";

function snap(partial: Partial<InstanceSnapshot>): InstanceSnapshot {
  return {
    ...TEST_SNAPSHOT_SHELL,
    instance_id: "QQ-1",
    title: "t",
    workflow: TEST_WORKFLOW,
    pack_version: "pv1",
    state: "rfq_sending",
    version: 1,
    stages: [],
    participants: [],
    my_roles: ["buyer"],
    pending: [],
    artifacts: [
      {
        artifact_id: "a1",
        artifact_type: "type_outbound",
        name: "Outbound draft",
        latest_version: 1,
        status: "draft",
        view: { type: "message_composer", fields: [] },
        versions: [],
      },
    ],
    turns: [],
    cursor: "0",
    ...partial,
  };
}

describe("showSendRfqsBar", () => {
  it("hides send when a task retry card is open", () => {
    expect(showSendRfqsBar(snap({}))).toBe(true);
    const retryPending = {
      pending_id: "p1",
      instance_id: "QQ-1",
      kind: "decision" as const,
      event: "task.retry",
      status: "open" as const,
      title: "Retry",
      for_role: "buyer",
      created_at: "2026-01-01T00:00:00Z",
    };
    expect(showSendRfqsBar(snap({ pending: [retryPending] }))).toBe(false);
    expect(hasOpenTaskRetry(snap({ pending: [retryPending] }))).toBe(true);
  });
});
