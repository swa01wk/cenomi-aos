import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ToolActivity } from "./ToolActivity";

describe("ToolActivity", () => {
  it("shows label and state as words", () => {
    render(
      <ToolActivity
        activity={{
          instance_id: "i1",
          attempt_id: "a1",
          tool: "search",
          label: "Searching records",
          state: "allowed",
        }}
      />,
    );
    expect(screen.getByText("Searching records · allowed")).toBeInTheDocument();
  });
});
