import { describe, expect, it } from "vitest";
import type { components } from "../api/schema";
import {
  countJobsNeedingViewer,
  jobNeedsViewerAction,
  pendingActionLabel,
  sortJobsForViewer,
} from "./instanceAttention";
import { TEST_WORKFLOW } from "./testJobFixtures";

type Job = components["schemas"]["InstanceSummary"];

function job(id: string, waiting_on?: Job["waiting_on"], last = "2026-01-02T00:00:00Z"): Job {
  return {
    instance_id: id,
    title: id,
    workflow: TEST_WORKFLOW,
    state: "shortlisting",
    state_label: "shortlisting",
    version: 1,
    waiting_on,
    last_activity_at: last,
  };
}

describe("instanceAttention", () => {
  it("detects when the viewer owns the open pending", () => {
    expect(jobNeedsViewerAction(job("a", { kind: "person", person_id: "noura" }), "noura")).toBe(true);
    expect(jobNeedsViewerAction(job("a", { kind: "person", person_id: "faisal" }), "noura")).toBe(false);
    expect(jobNeedsViewerAction(job("a", { kind: "task" }), "noura")).toBe(false);
  });

  it("sorts needs-action jobs first", () => {
    const sorted = sortJobsForViewer(
      [
        job("idle", { kind: "task" }, "2026-01-03T00:00:00Z"),
        job("yours", { kind: "person", person_id: "noura" }, "2026-01-01T00:00:00Z"),
      ],
      "noura",
    );
    expect(sorted.map((j) => j.instance_id)).toEqual(["yours", "idle"]);
  });

  it("uses pending title when present", () => {
    expect(pendingActionLabel(job("a", { kind: "person", person_id: "n", label: "Confirm shortlist" }))).toBe(
      "Confirm shortlist",
    );
  });

  it("counts jobs needing the viewer", () => {
    const jobs = [job("a", { kind: "person", person_id: "noura" }), job("b", { kind: "task" })];
    expect(countJobsNeedingViewer(jobs, "noura")).toBe(1);
  });
});
