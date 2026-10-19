import { useState } from "react";
import type { components } from "../api/schema";
import { ApiProblemError } from "../api/problems";
import { fieldErrorsFromProblem } from "../components";
import { Button, ChainSteps, FieldError, Panel } from "../components";
import { when } from "../lib/ui";

type PublishRequest = components["schemas"]["PublishRequest"];

export function PublishRequestPanel({
  request,
  packVersionLabel,
  personName,
  onApprove,
  onReject,
  showImmutableNote,
}: {
  request: PublishRequest;
  packVersionLabel: string;
  personName: (id: string) => string;
  onApprove: (part: PublishRequest["parts"][number]["part"]) => Promise<void>;
  onReject: (reason: string) => Promise<void>;
  showImmutableNote: boolean;
}) {
  const [busyPart, setBusyPart] = useState<string | null>(null);
  const [rejectReason, setRejectReason] = useState<Record<string, string>>({});
  const [fieldError, setFieldError] = useState<string | null>(null);

  const runApprove = async (part: PublishRequest["parts"][number]["part"]) => {
    setBusyPart(`approve:${part}`);
    setFieldError(null);
    try {
      await onApprove(part);
    } finally {
      setBusyPart(null);
    }
  };

  const runReject = async (part: PublishRequest["parts"][number]["part"]) => {
    const reason = (rejectReason[part] ?? "").trim();
    if (reason.length < 3) {
      setFieldError("Reason must be at least 3 characters.");
      return;
    }
    setBusyPart(`reject:${part}`);
    setFieldError(null);
    try {
      await onReject(reason);
      setRejectReason((r) => ({ ...r, [part]: "" }));
    } catch (e) {
      if (e instanceof ApiProblemError && e.problem.status === 422) {
        const errs = fieldErrorsFromProblem(e.problem);
        setFieldError(errs.get("reason") ?? e.problem.detail ?? e.problem.title);
        return;
      }
      throw e;
    } finally {
      setBusyPart(null);
    }
  };

  return (
    <Panel
      title={`Publish request ${request.id}`}
      header={
        <span className="muted" style={{ fontSize: 13 }}>
          {packVersionLabel} · requested by {personName(request.requested_by)}
          {request.requested_at ? ` · ${when(request.requested_at)}` : ""}
        </span>
      }
    >
      <ChainSteps
        parts={request.parts}
        formatPerson={personName}
        renderPartActions={(part) =>
          part.status === "open" ? (
            <div style={{ display: "flex", flexWrap: "wrap", alignItems: "flex-end", gap: 8, flex: "1 1 240px" }}>
              <Button
                variant="primary"
                disabledReason={busyPart !== null ? "Another action is in progress" : undefined}
                onClick={() => void runApprove(part.part)}
              >
                {busyPart === `approve:${part.part}` ? "Approving…" : "Approve"}
              </Button>
              <label style={{ display: "flex", flexDirection: "column", gap: 4, flex: "1 1 160px" }}>
                <span className="sr-only">Reject reason for {part.part}</span>
                <input
                  type="text"
                  value={rejectReason[part.part] ?? ""}
                  onChange={(e) => setRejectReason((r) => ({ ...r, [part.part]: e.target.value }))}
                  placeholder="Reason if rejecting"
                  aria-invalid={fieldError ? true : undefined}
                  style={{ height: 40, padding: "0 12px", borderRadius: 8, border: "1px solid var(--line)" }}
                />
              </label>
              <Button
                variant="danger"
                disabledReason={busyPart !== null ? "Another action is in progress" : undefined}
                onClick={() => void runReject(part.part)}
              >
                {busyPart === `reject:${part.part}` ? "Rejecting…" : "Reject"}
              </Button>
              {fieldError && <FieldError id={`reject-${part.part}`} message={fieldError} />}
            </div>
          ) : null
        }
      />
      {showImmutableNote && (
        <p className="muted" style={{ margin: "12px 0 0", fontSize: 12 }}>
          Published versions are immutable. A change becomes the next version; running work stays on the version it
          started with.
        </p>
      )}
    </Panel>
  );
}
