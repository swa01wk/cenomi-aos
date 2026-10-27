import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ThinkingStatus, formatElapsed } from "./ThinkingStatus";

describe("ThinkingStatus", () => {
  afterEach(() => {
    cleanup();
    vi.useRealTimers();
  });

  it("starts on Thinking and moves to the next phrase", () => {
    vi.useFakeTimers();
    render(<ThinkingStatus />);
    expect(screen.getByRole("status").textContent).toContain("Thinking");
    act(() => {
      vi.advanceTimersByTime(2400);
    });
    expect(screen.getByRole("status").textContent).toContain("Meticulating");
  });

  it("adds one displayed second every 1.5 seconds", () => {
    vi.useFakeTimers();
    render(<ThinkingStatus />);
    expect(screen.getByRole("status").textContent).toContain("0s");
    act(() => {
      vi.advanceTimersByTime(1499);
    });
    expect(screen.getByRole("status").textContent).toContain("0s");
    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(screen.getByRole("status").textContent).toContain("1s");
    act(() => {
      vi.advanceTimersByTime(1500);
    });
    expect(screen.getByRole("status").textContent).toContain("2s");
  });

  it("warns after the displayed time runs long", () => {
    vi.useFakeTimers();
    render(<ThinkingStatus />);
    act(() => {
      vi.advanceTimersByTime(89 * 1500);
    });
    expect(screen.queryByText(/longer than usual/)).toBeNull();
    act(() => {
      vi.advanceTimersByTime(1500);
    });
    expect(screen.getByRole("status").textContent).toContain("1m 30s");
    expect(screen.getByText(/longer than usual/)).toBeInTheDocument();
  });

  it("formats minutes", () => {
    expect(formatElapsed(5)).toBe("5s");
    expect(formatElapsed(125)).toBe("2m 05s");
  });
});
