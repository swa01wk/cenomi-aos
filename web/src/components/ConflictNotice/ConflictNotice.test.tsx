import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ConflictNotice } from "./ConflictNotice";

describe("ConflictNotice", () => {
  it("calls onReload", () => {
    const onReload = vi.fn();
    render(<ConflictNotice title="Changed" onReload={onReload} />);
    fireEvent.click(screen.getByRole("button", { name: "Reload" }));
    expect(onReload).toHaveBeenCalled();
  });
});
