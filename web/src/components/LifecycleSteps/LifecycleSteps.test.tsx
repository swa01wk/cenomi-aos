import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { LifecycleSteps } from "./LifecycleSteps";

describe("LifecycleSteps", () => {
  it("shows meta for a step", () => {
    render(
      <LifecycleSteps steps={[{ state: "DRAFT", status: "done", meta: "1 Jan · ready" }]} />,
    );
    expect(screen.getByText("1 Jan · ready")).toBeInTheDocument();
  });
});
