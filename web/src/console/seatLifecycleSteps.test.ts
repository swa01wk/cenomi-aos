import { describe, expect, it } from "vitest";
import { buildSeatLifecycleSteps } from "./seatLifecycleSteps";

const fmt = (h: { at?: string; by?: string }) => `${h.at ?? ""} · ${h.by ?? ""}`;

describe("buildSeatLifecycleSteps", () => {
  it("marks current state and meta from latest transition into each step", () => {
    const history = [
      { from: "DRAFT", to: "CONFIGURED", by: "alice", at: "2026-01-02T10:00:00Z" },
      { from: "CONFIGURED", to: "TESTING", by: "alice", at: "2026-01-03T10:00:00Z" },
      { from: "TESTING", to: "APPROVED", by: "risk", at: "2026-01-04T10:00:00Z" },
    ];
    const steps = buildSeatLifecycleSteps("APPROVED", history, fmt);
    expect(steps.find((s) => s.state === "DRAFT")?.status).toBe("done");
    expect(steps.find((s) => s.state === "APPROVED")?.status).toBe("current");
    expect(steps.find((s) => s.state === "ACTIVE")?.status).toBe("next");
    expect(steps.find((s) => s.state === "CONFIGURED")?.meta).toContain("alice");
  });

  it("uses the latest transition when history has multiple entries to the same state", () => {
    const history = [
      { from: "DRAFT", to: "CONFIGURED", by: "first", at: "2026-01-01T10:00:00Z" },
      { from: "DRAFT", to: "CONFIGURED", by: "second", at: "2026-01-02T10:00:00Z" },
    ];
    const steps = buildSeatLifecycleSteps("CONFIGURED", history, fmt);
    expect(steps.find((s) => s.state === "CONFIGURED")?.meta).toContain("second");
  });

  it("shows five as reached per history when state is outside the main path", () => {
    const history = [
      { from: "DRAFT", to: "CONFIGURED", by: "a", at: "2026-01-01T10:00:00Z" },
      { from: "CONFIGURED", to: "TESTING", by: "a", at: "2026-01-02T10:00:00Z" },
      { from: "TESTING", to: "APPROVED", by: "r", at: "2026-01-03T10:00:00Z" },
      { from: "APPROVED", to: "ACTIVE", by: "o", at: "2026-01-04T10:00:00Z" },
      { from: "ACTIVE", to: "PAUSED", by: "o", at: "2026-01-05T10:00:00Z" },
    ];
    const steps = buildSeatLifecycleSteps("PAUSED", history, fmt);
    expect(steps.every((s) => s.status === "done")).toBe(true);
    expect(steps.find((s) => s.state === "ACTIVE")?.meta).toContain("o");
  });

  it("leaves unreached steps as next when state is outside the main path", () => {
    const history = [{ from: "DRAFT", to: "CONFIGURED", by: "a", at: "2026-01-01T10:00:00Z" }];
    const steps = buildSeatLifecycleSteps("KILLED", history, fmt);
    expect(steps.find((s) => s.state === "CONFIGURED")?.status).toBe("done");
    expect(steps.find((s) => s.state === "TESTING")?.status).toBe("next");
  });
});
