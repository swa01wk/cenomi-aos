import { describe, expect, it } from "vitest";
import { TEST_WORKFLOW } from "../testJobFixtures";
import { jobStepGuide, stageGuideIsLive, stepGuideShowsWaitingDots } from "./stageGuideLogic";
import type { InstanceSnapshot } from "./jobStreamReducer";

function snap(partial: Partial<InstanceSnapshot> & Pick<InstanceSnapshot, "state">): InstanceSnapshot {
  return {
    instance_id: "QQ-1",
    title: "Test",
    workflow: TEST_WORKFLOW,
    pack_version: "p@1",
    version: 1,
    stages: [
      { state: "awaiting_quotes", label: "Awaiting replies", status: "current" },
      { state: "closed", label: "Closed", status: "next" },
    ],
    participants: [],
    my_roles: ["buyer"],
    pending: [],
    artifacts: [],
    turns: [],
    cursor: "0",
    ...partial,
  };
}

describe("jobStepGuide", () => {
  it("uses the pending card title when a decision is open", () => {
    const g = jobStepGuide(
      snap({
        state: "comparison",
        stages: [
          { state: "comparison", label: "Comparison", status: "current" },
          { state: "closed", label: "Closed", status: "next" },
        ],
        pending: [
          {
            pending_id: "p1",
            instance_id: "QQ-1",
            kind: "decision",
            event: "decision.party_selected",
            title: "Select the winning row",
            for_role: "buyer",
            status: "open",
            created_at: "2026-10-28T08:00:00Z",
          },
        ],
      }),
      { agentBusy: false, openPendingForYou: 1 },
    );
    expect(g?.kind).toBe("action");
    expect(g?.title).toBe("Select the winning row");
  });

  it("does not duplicate a generic banner when a decision card is shown in the thread", () => {
    const g = jobStepGuide(snap({ state: "awaiting_quotes" }), { agentBusy: false, openPendingForYou: 1 });
    expect(g).toBeNull();
  });

  it("explains waiting after outbound messages are sent", () => {
    const g = jobStepGuide(snap({ state: "awaiting_quotes" }), { agentBusy: false, openPendingForYou: 0 });
    expect(g?.kind).toBe("wait");
    expect(g?.title).toMatch(/Waiting for replies/);
    expect(g?.detail).toMatch(/digital worker/i);
  });

  it("shows progress while the agent is busy", () => {
    const g = jobStepGuide(snap({ state: "shortlisting" }), { agentBusy: true, openPendingForYou: 0 });
    expect(g?.kind).toBe("progress");
    expect(g?.title).toMatch(/in progress/);
  });

  it("marks shortlisting stage guide as live while work runs", () => {
    const snapshot = snap({ state: "shortlisting" });
    const g = jobStepGuide(snapshot, { agentBusy: false, openPendingForYou: 0 });
    expect(g?.title).toMatch(/Building the ranked list/);
    expect(g && stageGuideIsLive(g, snapshot.state)).toBe(true);
  });

  it("tells the requester a buyer must act once the sheet exists", () => {
    const snapshot = snap({
      state: "shortlisting",
      my_roles: ["requester"],
      artifacts: [
        {
          artifact_id: "art_sl",
          artifact_type: "type_ranked",
          name: "Ranked list",
          latest_version: 8,
          status: "draft",
          view: { type: "sheet", row_key: "party_id", columns: [], fields: [] },
          versions: [],
        },
      ],
    });
    const g = jobStepGuide(snapshot, { agentBusy: false, openPendingForYou: 0 });
    expect(g?.kind).toBe("wait");
    expect(g?.detail).toMatch(/Team queue/i);
    expect(g && stageGuideIsLive(g, snapshot.state)).toBe(false);
  });

  it("shows waiting dots on progress and open wait guides, not when closed", () => {
    const intake = jobStepGuide(snap({ state: "intake" }), { agentBusy: false, openPendingForYou: 0 });
    expect(intake && stepGuideShowsWaitingDots(intake, "intake")).toBe(true);
    const waiting = jobStepGuide(snap({ state: "awaiting_quotes" }), { agentBusy: false, openPendingForYou: 0 });
    expect(waiting && stepGuideShowsWaitingDots(waiting, "awaiting_quotes")).toBe(true);
    const closed = jobStepGuide(snap({ state: "closed" }), { agentBusy: false, openPendingForYou: 0 });
    expect(closed?.kind).toBe("complete");
    expect(closed && stepGuideShowsWaitingDots(closed, "closed")).toBe(false);
  });
});
