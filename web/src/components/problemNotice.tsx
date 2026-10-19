import type { Problem } from "../api/problems";
import { fieldErrorsFromProblem } from "./fieldErrors";

export type SessionNoticeProps = { title?: string; detail?: string };
export type RefusalNoticeProps = {
  title: string;
  detail?: string;
  rule?: string;
  decisionId?: string;
};
export type SeatNoticeProps = {
  code: "seat_not_active" | "kill_switch_active";
  title: string;
  detail?: string;
};
export type ConflictNoticeProps = { title: string; detail?: string };
export type FieldsNoticeProps = { fields: { name: string; message: string }[] };
export type ErrorNoticeProps = { title: string; detail?: string; traceId?: string; retryable?: boolean };

export type ProblemNoticeDescriptor =
  | { kind: "session"; props: SessionNoticeProps }
  | { kind: "refusal"; props: RefusalNoticeProps }
  | { kind: "seat"; props: SeatNoticeProps }
  | { kind: "conflict"; props: ConflictNoticeProps }
  | { kind: "fields"; props: FieldsNoticeProps }
  | { kind: "error"; props: ErrorNoticeProps };

const REFUSAL_CODES = new Set([
  "not_permitted",
  "policy_denied",
  "policy_never",
  "segregation_of_duties",
]);

const CONFLICT_CODES = new Set(["stale_version", "already_claimed", "approval_stale"]);

export function problemNotice(problem: Problem): ProblemNoticeDescriptor {
  if (problem.status === 401 && problem.code === "unauthenticated") {
    return {
      kind: "session",
      props: { title: problem.title, detail: problem.detail },
    };
  }

  if (problem.status === 403 && REFUSAL_CODES.has(problem.code)) {
    return {
      kind: "refusal",
      props: {
        title: problem.title,
        detail: problem.detail,
        rule: problem.rule,
        decisionId: problem.decision_id,
      },
    };
  }

  if (problem.status === 403 && (problem.code === "seat_not_active" || problem.code === "kill_switch_active")) {
    return {
      kind: "seat",
      props: {
        code: problem.code,
        title: problem.title,
        detail: problem.detail,
      },
    };
  }

  if (problem.status === 409 && CONFLICT_CODES.has(problem.code)) {
    return {
      kind: "conflict",
      props: { title: problem.title, detail: problem.detail },
    };
  }

  if (problem.status === 422 && problem.code === "validation_failed") {
    const fields = [...fieldErrorsFromProblem(problem).entries()].map(([name, message]) => ({ name, message }));
    return { kind: "fields", props: { fields } };
  }

  if ((problem.status === 429 || problem.status === 503) && problem.code === "unavailable") {
    return {
      kind: "error",
      props: { title: problem.title, detail: problem.detail, retryable: true },
    };
  }

  if (problem.status >= 500 || problem.code === "internal") {
    return {
      kind: "error",
      props: { title: problem.title, detail: problem.detail, traceId: problem.trace_id, retryable: true },
    };
  }

  return {
    kind: "error",
    props: { title: problem.title, detail: problem.detail, traceId: problem.trace_id, retryable: true },
  };
}
