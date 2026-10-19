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
});
