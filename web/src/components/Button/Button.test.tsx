import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Button } from "./Button";

describe("Button", () => {
  afterEach(() => cleanup());
  it("calls onClick when enabled", () => {
    const onClick = vi.fn();
    render(<Button onClick={onClick}>Go</Button>);
    fireEvent.click(screen.getByRole("button", { name: "Go" }));
    expect(onClick).toHaveBeenCalled();
  });

  it("does not call onClick when disabled with reason; stays focusable with accessible description", async () => {
    const onClick = vi.fn();
    render(
      <Button disabledReason="Not allowed yet" onClick={onClick}>
        Save
      </Button>,
    );
    const btn = screen.getByRole("button", { name: /Save/ });
    expect(btn).toHaveAttribute("aria-disabled", "true");
    expect(btn).not.toHaveAttribute("disabled");
    fireEvent.click(btn);
    expect(onClick).not.toHaveBeenCalled();
    btn.focus();
    expect(btn).toHaveFocus();
    expect(btn).toHaveAccessibleDescription("Not allowed yet");
  });
});
