import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { describe, expect, it } from "vitest";
import { StatTile } from "./StatTile";

describe("StatTile", () => {
  it("renders value", () => {
    render(<StatTile label="Open" value="3" />);
    expect(screen.getByText("3")).toBeInTheDocument();
  });

  it("links when href set", () => {
    render(
      <MemoryRouter>
        <StatTile label="Open" value="3" href="/x" />
      </MemoryRouter>,
    );
    expect(screen.getByRole("link")).toHaveAttribute("href", "/x");
  });
});
