import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { StatusPill } from "./StatusPill";

describe("StatusPill", () => {
  it("prints state verbatim", () => {
    render(<StatusPill state="publish_requested" />);
    expect(screen.getByText("publish_requested")).toBeInTheDocument();
  });
});
