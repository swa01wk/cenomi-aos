import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AgentWorkStatus } from "./AgentWorkStatus";

describe("AgentWorkStatus", () => {
  afterEach(() => {
    cleanup();
    vi.useRealTimers();
  });

  it("shows a named step list", () => {
    render(<AgentWorkStatus workflowState="intake" isFirstExchange />);
    expect(screen.getByRole("status")).toHaveTextContent(/Reading your request/);
    expect(screen.getByText(/Drafting the brief/)).toBeInTheDocument();
  });

  it("shows async guidance after twenty seconds", () => {
    vi.useFakeTimers();
    render(<AgentWorkStatus workflowState="intake" isFirstExchange={false} />);
    act(() => {
      vi.advanceTimersByTime(20_000);
    });
    expect(screen.getByText(/leave this page/i)).toBeInTheDocument();
  });
});
