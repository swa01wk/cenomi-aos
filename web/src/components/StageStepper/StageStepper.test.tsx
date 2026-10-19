import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { StageStepper } from "./StageStepper";

describe("StageStepper", () => {
  it("marks current step", () => {
    render(
      <StageStepper
        stages={[
          { state: "a", label: "Alpha", status: "done" },
          { state: "b", label: "Beta", status: "current" },
        ]}
      />,
    );
    expect(screen.getByText("Beta")).toHaveAttribute("aria-current", "step");
  });
});
