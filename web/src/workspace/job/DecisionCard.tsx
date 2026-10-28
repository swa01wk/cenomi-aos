import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { client } from "../../api/client";
import { ApiProblemError, type Problem } from "../../api/problems";
import type { components } from "../../api/schema";
import { Button } from "../../components";
import { newClientTurnId } from "../../components/clientTurnId";
import { workspaceKeys } from "../useWorkspaceQueries";
import { formatFieldValue } from "./views/formatFieldValue";
import { defaultDecisionNote } from "./decisionCardDefaults";
import styles from "./DecisionCard.module.css";

type PendingItem = components["schemas"]["PendingItem"];
type ArtifactView = components["schemas"]["ArtifactView"];

export function DecisionCard({
  pending,
  view,
  onApprove,
  variant = "default",
}: {
  pending: PendingItem;
  view?: ArtifactView;
  variant?: "default" | "retry";
  onApprove: (input: {
    pendingId: string;
    value: string;
    artifactVersion?: number;
    note?: string;
    selection?: string[];
    idempotencyKey: string;
  }) => Promise<void>;
}) {
  const [note, setNote] = useState(() => defaultDecisionNote(pending));

  useEffect(() => {
    setNote(defaultDecisionNote(pending));
  }, [pending.pending_id, pending.event, pending.title]);
  const [selected, setSelected] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<Problem | null>(null);
  const keyRef = useRef<string | null>(null);
  const preferConfirm = pending.event !== "task.retry";
  const option =
    (preferConfirm ? pending.options?.find((o) => o.value === "confirm") : pending.options?.[0]) ??
    pending.options?.[0];
  const value = option?.value ?? "confirm";
  const actionLabel = option?.label ?? (pending.event === "task.retry" ? "Retry this step" : "Approve");
  const minimum = pending.select_min ?? 0;
  const needsChoice = minimum > 0;
  const short = needsChoice && selected.length < minimum;

  const approve = async () => {
    if (busy || short) return;
    if (!keyRef.current) keyRef.current = newClientTurnId();
    setBusy(true);
    setProblem(null);
    try {
      await onApprove({
        pendingId: pending.pending_id,
        value,
        artifactVersion: pending.artifact_ref?.version,
        note: note.trim() || undefined,
        selection: needsChoice ? selected : undefined,
        idempotencyKey: keyRef.current,
      });
    } catch (e) {
      keyRef.current = null;
      if (e instanceof ApiProblemError) setProblem(e.problem);
      else
        setProblem({
          type: "about:blank",
          title: "Could not approve",
          status: 500,
          code: "internal",
          detail: String(e),
        });
    } finally {
      setBusy(false);
    }
  };

  const reason = busy ? "Saving" : short ? pending.detail || `Choose at least ${minimum}` : undefined;
  const compactRetry = variant === "retry" || pending.event === "task.retry";
  const [showNote, setShowNote] = useState(!compactRetry);

  return (
    <div
      className={[styles.card, compactRetry ? styles.card_retry : ""].filter(Boolean).join(" ")}
      role="group"
      aria-label={pending.title}
    >
      <p className={styles.title}>
        {compactRetry ? pending.title.replace(/^Retry:\s*/i, "") : pending.title}
      </p>
      {pending.detail && !compactRetry ? <p className={styles.detail}>{pending.detail}</p> : null}
      {compactRetry && pending.detail ? <p className={styles.detailMuted}>{pending.detail}</p> : null}
      {needsChoice && pending.artifact_ref?.artifact_id && view?.row_key ? (
        <RowChoices
          artifactId={pending.artifact_ref.artifact_id}
          version={pending.artifact_ref.version ?? 1}
          view={view}
          rowKey={view.row_key}
          selected={selected}
          onChange={setSelected}
        />
      ) : null}
      {showNote ? (
        <label>
          <span className="ws-sr-only">Comment</span>
          <textarea
            className={styles.comment}
            value={note}
            placeholder="Comment (optional)"
            maxLength={2000}
            onChange={(e) => setNote(e.target.value)}
          />
        </label>
      ) : (
        <button type="button" className={styles.noteToggle} onClick={() => setShowNote(true)}>
          Add a note (optional)
        </button>
      )}
      <div>
        <Button type="button" variant={compactRetry ? "secondary" : "primary"} disabledReason={reason} onClick={() => void approve()}>
          {busy ? "Saving…" : compactRetry ? "Retry this step" : actionLabel}
        </Button>
      </div>
      {problem && <p className={styles.error}>{problem.detail || problem.title}</p>}
    </div>
  );
}

function RowChoices({
  artifactId,
  version,
  view,
  rowKey,
  selected,
  onChange,
}: {
  artifactId: string;
  version: number;
  view: ArtifactView;
  rowKey: string;
  selected: string[];
  onChange: (next: string[]) => void;
}) {
  const content = useQuery({
    queryKey: workspaceKeys.artifactVersion(artifactId, version),
    queryFn: async () => {
      const { data, error } = await client.GET("/artifacts/{id}/versions/{version}", {
        params: { path: { id: artifactId, version } },
      });
      if (error) throw error;
      return data!;
    },
  });
  const rows = Array.isArray((content.data?.content as { rows?: unknown } | undefined)?.rows)
    ? ((content.data!.content as { rows: Record<string, unknown>[] }).rows)
    : [];
  const order = (view.columns?.length ? view.columns : view.fields.map((f) => f.name)).slice(0, 2);
  const byName = new Map(view.fields.map((f) => [f.name, f]));

  if (content.isLoading) return <p className={styles.detail}>Loading the list…</p>;
  if (content.isError) return <p className={styles.error}>The list could not be loaded.</p>;

  return (
    <div className={styles.choices} role="group" aria-label="Rows">
      {rows.map((row) => {
        const key = row[rowKey];
        if (key == null || key === "") return null;
        const id = String(key);
        const label = order
          .map((name) => {
            const field = byName.get(name);
            return field ? formatFieldValue(field, row[name]).text : "";
          })
          .filter((text) => text && text !== "—")
          .join(" · ");
        return (
          <label key={id} className={styles.choice}>
            <input
              type="checkbox"
              checked={selected.includes(id)}
              onChange={() =>
                onChange(selected.includes(id) ? selected.filter((item) => item !== id) : [...selected, id])
              }
            />
            <span>{label || id}</span>
          </label>
        );
      })}
    </div>
  );
}
