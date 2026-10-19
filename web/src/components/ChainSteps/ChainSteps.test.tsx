import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ChainSteps } from "./ChainSteps";

describe("ChainSteps", () => {
  it("lists parts", () => {
    render(
      <ChainSteps
        parts={[{ part: "policies", role: "risk", status: "open" }]}
      />,
    );
    expect(screen.getByText(/Policies/)).toBeInTheDocument();
  });

  it("shows approver and time when approved", () => {
    render(
      <ChainSteps
        parts={[
          {
            part: "policies",
            role: "risk",
            status: "approved",
            by: "risk_reviewer",
            at: "2026-01-15T10:00:00.000Z",
          },
        ]}
        formatPerson={() => "Risk reviewer"}
      />,
    );
    expect(screen.getByText(/Risk reviewer/)).toBeInTheDocument();
    expect(screen.getByText(/approved/)).toBeInTheDocument();
  });
});
