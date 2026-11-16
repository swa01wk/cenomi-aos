import { beforeEach, describe, expect, it } from "vitest";
import { markCoordinatorHandedOff, openChatInstanceForSeat } from "./openPersonChat";
import type { components } from "../api/schema";

type Job = components["schemas"]["InstanceSummary"];
type Worker = components["schemas"]["DigitalWorker"];

const entryWorker: Worker = {
  seat: "seat_workspace_coordinator",
  display_name: "Sam",
  colleague_name: "Sam Taylor",
  title: "Coordinator",
  version: 1,
  state: "ACTIVE",
  workflows: [{ name: "workspace_coordination", title: "Coord", description: "", intake_hints: [] }],
};

function job(partial: Partial<Job> & Pick<Job, "instance_id">): Job {
  return {
    title: "hi",
    workflow: "workspace_coordination",
    seat: "seat_workspace_coordinator",
    state: "chat",
    state_label: "Chat",
    version: 1,
    last_activity_at: "2026-10-29T08:00:00Z",
    started_at: "2026-10-29T08:00:00Z",
    ...partial,
  };
}

describe("openPersonChat", () => {
  beforeEach(() => {
    sessionStorage.clear();
  });

  it("opens active coordinator chat and skips handed-off threads", () => {
    const jobs = [
      job({ instance_id: "WC-OLD", last_activity_at: "2026-10-29T07:00:00Z" }),
      job({ instance_id: "WC-NEW", last_activity_at: "2026-10-29T09:00:00Z" }),
    ];
    expect(openChatInstanceForSeat("seat_workspace_coordinator", jobs, entryWorker)).toBe("WC-NEW");
    markCoordinatorHandedOff("WC-NEW");
    expect(openChatInstanceForSeat("seat_workspace_coordinator", jobs, entryWorker)).toBe("WC-OLD");
  });

  it("does not resume misrouted Quick Quote intake that looks like an RFP", () => {
    const specialist: Worker = {
      seat: "seat_sourcing_poc",
      display_name: "Noor",
      colleague_name: "Noor",
      title: "Sourcing",
      version: 1,
      state: "ACTIVE",
      workflows: [{ name: "quick_quote", title: "QQ", description: "", intake_hints: ["quote"] }],
    };
    const jobs: Job[] = [
      {
        instance_id: "QQ-0014",
        title: "RFP: Full redesign of Cenomi Malls public marketing website",
        workflow: "quick_quote",
        seat: "seat_sourcing_poc",
        state: "intake",
        state_label: "Intake",
        version: 1,
        last_activity_at: "2026-11-03T09:00:00Z",
        started_at: "2026-11-03T09:00:00Z",
      },
    ];
    expect(openChatInstanceForSeat("seat_sourcing_poc", jobs, specialist)).toBeUndefined();
  });
});
