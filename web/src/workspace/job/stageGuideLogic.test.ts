import { describe, expect, it } from "vitest";
import { TEST_SNAPSHOT_SHELL, TEST_WORKFLOW } from "../testJobFixtures";
import {
  jobStepGuide,
  quickQuoteRfpMisrouteNotice,
  stageGuideIsLive,
  stepGuideShowsWaitingDots,
} from "./stageGuideLogic";
import type { InstanceSnapshot } from "./jobStreamReducer";

function snap(partial: Partial<InstanceSnapshot> & Pick<InstanceSnapshot, "state">): InstanceSnapshot {
  return {
    ...TEST_SNAPSHOT_SHELL,
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
    expect(g?.detail).toMatch(/RFQs sent|from your brief|sourcing inbox/i);
  });

  it("shows progress while the agent is busy", () => {
    const g = jobStepGuide(snap({ state: "shortlisting" }), { agentBusy: true, openPendingForYou: 0 });
    expect(g?.kind).toBe("progress");
    expect(g?.title).toMatch(/in progress/);
  });

  it("keeps awaiting-quotes wait guide visible while the agent is busy", () => {
    const g = jobStepGuide(snap({ state: "awaiting_quotes" }), { agentBusy: true, openPendingForYou: 0 });
    expect(g?.kind).toBe("wait");
    expect(g?.title).toMatch(/Waiting for replies/);
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

  it("defers ranked-list nudge while the specialist waits on a reply", () => {
    const snapshot = snap({
      state: "shortlisting",
      my_roles: ["requester"],
      turns: [
        {
          turn_id: "t1",
          seq: 1,
          at: "2026-10-29T12:00:00Z",
          author: { kind: "seat", id: "seat_sourcing_poc", name: "Noor" },
          blocks: [{ kind: "text", text: "Reply with 1 or 2." }],
        },
      ],
      artifacts: [
        {
          artifact_id: "art_sl",
          artifact_type: "type_ranked",
          name: "Ranked list",
          latest_version: 1,
          status: "draft",
          view: { type: "sheet", row_key: "party_id", columns: [], fields: [] },
          versions: [],
        },
      ],
    });
    const g = jobStepGuide(snapshot, { agentBusy: false, openPendingForYou: 0 });
    expect(g?.title).toMatch(/Waiting on your reply/i);
  });

  it("does not show a footer guide during chat-only workflow states", () => {
    expect(jobStepGuide(snap({ state: "conversation" }), { agentBusy: false, openPendingForYou: 0 })).toBeNull();
    expect(jobStepGuide(snap({ state: "chat" }), { agentBusy: false, openPendingForYou: 0 })).toBeNull();
  });

  it("guides intake toward brief review when a draft exists", () => {
    const snapshot = snap({
      state: "intake",
      artifacts: [
        {
          artifact_id: "art_brief",
          artifact_type: "brief",
          name: "Brief",
          latest_version: 1,
          status: "draft",
          view: { type: "form", fields: [] },
        },
      ],
    });
    const g = jobStepGuide(snapshot, { agentBusy: false, openPendingForYou: 0 });
    expect(g?.kind).toBe("action");
    expect(g?.title).toMatch(/Review your brief/i);
  });

  it("warns on Quick Quote jobs titled like an RFP", () => {
    const n = quickQuoteRfpMisrouteNotice(
      snap({
        state: "intake",
        workflow: "quick_quote",
        instance_id: "QQ-0006",
        title: "RFP – Full redesign of public marketing website",
      }),
    );
    expect(n?.kind).toBe("notice");
    expect(n?.detail).toMatch(/brief/i);
    expect(n?.detail).toMatch(/RFP-/);
  });

  it("shows CDO wait guide on sourcing_rfp when master RFP approval is open for Samir", () => {
    const g = jobStepGuide(
      snap({
        state: "master_rfp_drafting",
        workflow: "sourcing_rfp",
        instance_id: "RFP-0001",
        artifacts: [
          {
            artifact_id: "m1",
            artifact_type: "master_rfp",
            latest_version: 2,
            view: { type: "document", title: "Master RFP" },
          },
        ],
        pending: [
          {
            pending_id: "p1",
            instance_id: "RFP-0001",
            kind: "decision",
            event: "decision.master_rfp_confirmed",
            title: "Approve master RFP before invitations",
            for_role: "procurement_approver",
            status: "open",
            created_at: "2026-11-03T08:00:00Z",
          },
        ],
      }),
      { agentBusy: false, openPendingForYou: 0 },
    );
    expect(g?.kind).toBe("wait");
    expect(g?.title).toMatch(/CDO/i);
  });

  it("shows waiting dots on progress and open wait guides, not when closed", () => {
    const intakeBusy = jobStepGuide(snap({ state: "intake" }), { agentBusy: true, openPendingForYou: 0 });
    expect(intakeBusy && stepGuideShowsWaitingDots(intakeBusy, "intake")).toBe(true);
    const waiting = jobStepGuide(snap({ state: "awaiting_quotes" }), { agentBusy: false, openPendingForYou: 0 });
    expect(waiting && stepGuideShowsWaitingDots(waiting, "awaiting_quotes")).toBe(true);
    const closed = jobStepGuide(snap({ state: "closed" }), { agentBusy: false, openPendingForYou: 0 });
    expect(closed?.kind).toBe("complete");
    expect(closed && stepGuideShowsWaitingDots(closed, "closed")).toBe(false);
  });
});
