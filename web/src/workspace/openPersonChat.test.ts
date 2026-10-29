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
});
