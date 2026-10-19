import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { Problem } from "../api/problems";
import { ProblemNotice } from "./ProblemNotice/ProblemNotice";
import { problemNotice } from "./problemNotice";

function p(partial: Partial<Problem> & Pick<Problem, "status" | "code" | "title">): Problem {
  return { type: "about:blank", ...partial } as Problem;
}

describe("problemNotice", () => {
  it("401 unauthenticated → session", () => {
    expect(problemNotice(p({ status: 401, code: "unauthenticated", title: "Sign in required" })).kind).toBe("session");
  });

  it("403 not_permitted → refusal", () => {
    expect(problemNotice(p({ status: 403, code: "not_permitted", title: "Not allowed" })).kind).toBe("refusal");
  });

  it("403 policy_denied → refusal", () => {
    expect(problemNotice(p({ status: 403, code: "policy_denied", title: "Denied" })).kind).toBe("refusal");
  });

  it("403 policy_never → refusal", () => {
    expect(problemNotice(p({ status: 403, code: "policy_never", title: "Never" })).kind).toBe("refusal");
  });

  it("403 segregation_of_duties → refusal", () => {
    expect(problemNotice(p({ status: 403, code: "segregation_of_duties", title: "Segregation" })).kind).toBe("refusal");
  });

  it("403 seat_not_active → seat", () => {
    expect(problemNotice(p({ status: 403, code: "seat_not_active", title: "Paused" })).kind).toBe("seat");
  });

  it("403 kill_switch_active → seat", () => {
    expect(problemNotice(p({ status: 403, code: "kill_switch_active", title: "Stopped" })).kind).toBe("seat");
  });

  it("409 stale_version → conflict", () => {
    expect(problemNotice(p({ status: 409, code: "stale_version", title: "Stale" })).kind).toBe("conflict");
  });

  it("409 already_claimed → conflict", () => {
    expect(problemNotice(p({ status: 409, code: "already_claimed", title: "Claimed" })).kind).toBe("conflict");
  });

  it("409 approval_stale → conflict", () => {
    expect(problemNotice(p({ status: 409, code: "approval_stale", title: "Approval stale" })).kind).toBe("conflict");
  });

  it("422 validation_failed → fields", () => {
    const d = problemNotice(
      p({
        status: 422,
        code: "validation_failed",
        title: "Invalid",
        errors: [{ pointer: "/quantity", message: "Bad" }],
      }),
    );
    expect(d.kind).toBe("fields");
    if (d.kind === "fields") expect(d.props.fields[0]?.name).toBe("quantity");
  });

  it("503 unavailable → error retryable", () => {
    const d = problemNotice(p({ status: 503, code: "unavailable", title: "Down" }));
    expect(d.kind).toBe("error");
    if (d.kind === "error") expect(d.props.retryable).toBe(true);
  });

  it("429 unavailable → error retryable", () => {
    const d = problemNotice(p({ status: 429, code: "unavailable", title: "Rate limited" }));
    expect(d.kind).toBe("error");
    if (d.kind === "error") expect(d.props.retryable).toBe(true);
  });

  it("500 internal → error with trace", () => {
    const d = problemNotice(p({ status: 500, code: "internal", title: "Error", trace_id: "abc" }));
    expect(d.kind).toBe("error");
    if (d.kind === "error") expect(d.props.traceId).toBe("abc");
  });

  it("unknown code falls back to error banner", () => {
    render(<ProblemNotice problem={p({ status: 404, code: "not_found", title: "Missing", trace_id: "t1" })} onRetry={vi.fn()} />);
    expect(screen.getByRole("alert")).toHaveTextContent("Missing");
    expect(screen.getByText("t1")).toBeInTheDocument();
  });
});
