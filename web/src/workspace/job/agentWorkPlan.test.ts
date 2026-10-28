import { describe, expect, it } from "vitest";
import { buildAgentWorkStatus, formatElapsed } from "./agentWorkPlan";

describe("agentWorkPlan", () => {
  it("formats elapsed time", () => {
    expect(formatElapsed(5)).toBe("5s");
    expect(formatElapsed(125)).toBe("2m 05s");
  });

  it("uses named intake steps instead of a generic spinner label", () => {
    const model = buildAgentWorkStatus({
      workflowState: "intake",
      isFirstExchange: true,
      elapsedSec: 0,
    });
    expect(model.headline).toMatch(/Reading your request/);
    expect(model.steps.map((s) => s.label)).toContain("Drafting the brief");
    expect(model.expectation).toMatch(/about a minute/);
  });

  it("prefers the tool activity label when the worker reports one", () => {
    const model = buildAgentWorkStatus({
      workflowState: "intake",
      isFirstExchange: false,
      elapsedSec: 5,
      toolActivity: {
        instance_id: "QQ-1",
        attempt_id: "a1",
        tool: "erp_search",
        label: "Searching suppliers in the ERP",
        state: "allowed",
      },
    });
    expect(model.headline).toBe("Searching suppliers in the ERP");
  });

  it("shows async hint after twenty seconds", () => {
    const model = buildAgentWorkStatus({
      workflowState: "shortlisting",
      isFirstExchange: false,
      elapsedSec: 20,
    });
    expect(model.asyncHint).toBe(true);
  });
});
