import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { EmptyState } from "./EmptyState";

describe("EmptyState", () => {
  it("renders title and next step", () => {
    render(<EmptyState title="No jobs yet" nextStep="Start one from New job." />);
    expect(screen.getByText("No jobs yet")).toBeInTheDocument();
  });
});
