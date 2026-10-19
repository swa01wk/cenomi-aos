import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { PageHeader } from "./PageHeader";

describe("PageHeader", () => {
  it("renders title", () => {
    render(<PageHeader title="Jobs" />);
    expect(screen.getByRole("heading", { name: "Jobs" })).toBeInTheDocument();
  });
});
