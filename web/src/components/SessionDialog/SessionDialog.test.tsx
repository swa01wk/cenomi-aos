import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { SessionDialog } from "./SessionDialog";

describe("SessionDialog", () => {
  it("focuses Sign in when open", () => {
    render(<SessionDialog open onSignIn={vi.fn()} />);
    expect(screen.getByRole("button", { name: "Sign in" })).toHaveFocus();
  });
});
