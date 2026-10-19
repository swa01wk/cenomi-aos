import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { describe, expect, it } from "vitest";
import { RefusalNotice } from "./RefusalNotice";

describe("RefusalNotice", () => {
  it("shows decision link only with href", () => {
    const { rerender } = render(
      <MemoryRouter>
        <RefusalNotice title="No" decisionId="d1" />
      </MemoryRouter>,
    );
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
    rerender(
      <MemoryRouter>
        <RefusalNotice title="No" decisionId="d1" decisionHref="/console/policies/decisions/d1" />
      </MemoryRouter>,
    );
    expect(screen.getByRole("link", { name: "d1" })).toBeInTheDocument();
  });
});
