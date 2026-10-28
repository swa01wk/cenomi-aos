import { describe, expect, it } from "vitest";
import { jobHeaderBadge, stagesForDisplay } from "./jobLifecycle";

describe("jobLifecycle", () => {
  it("marks all stages done when closed", () => {
    const stages = [
      { state: "intake", label: "Intake", status: "done" as const },
      { state: "closed", label: "Closed", status: "current" as const },
    ];
    const out = stagesForDisplay(stages, "closed");
    expect(out.every((s) => s.status === "done")).toBe(true);
  });

  it("shows complete badge when closed", () => {
    const stages = [
      { state: "a", label: "A", status: "done" as const },
      { state: "closed", label: "Closed", status: "current" as const },
    ];
    expect(jobHeaderBadge(stages, "closed")).toMatch(/Complete · all 2 stages done/);
  });
});
