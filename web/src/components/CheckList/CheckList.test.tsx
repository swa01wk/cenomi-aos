import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { CheckList, checksFromSeatDetail } from "./CheckList";

describe("CheckList", () => {
  it("maps seat checks to pass/fail", () => {
    const items = checksFromSeatDetail([{ name: "limits", passed: true, detail: "ok" }]);
    render(<CheckList items={items} />);
    // The status word is for screen readers; the icon carries it visually.
    expect(screen.getByText("pass")).toBeInTheDocument();
    expect(screen.getByRole("listitem")).toHaveTextContent("limits");
    expect(screen.getByText("ok")).toBeInTheDocument();
  });
});
