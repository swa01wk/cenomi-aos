import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Panel } from "./Panel";

describe("Panel", () => {
  it("renders children", () => {
    render(<Panel title="Section">Body</Panel>);
    expect(screen.getByText("Body")).toBeInTheDocument();
  });
});
