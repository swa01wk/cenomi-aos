import { useEffect, useState } from "react";
import { Button } from "../../../components";
import { ApiProblemError } from "../../../api/problems";
import { proposalClarificationDraftBody, proposalClarificationDraftLabel } from "./proposalReplyLabels";
import type { ProposalReplyContent } from "./proposalReplyLabels";
import styles from "./views.module.css";

type Props = {
  content: ProposalReplyContent;
  artifactId: string;
  version: number;
  baseContent: Record<string, unknown>;
  canEdit: boolean;
  onSave?: (artifactId: string, baseVersion: number, content: Record<string, unknown>) => Promise<void>;
};

export function ClarificationNotesEditor({
  content,
  artifactId,
  version,
  baseContent,
  canEdit,
  onSave,
}: Props) {
  const fullNotes = String(content.notes ?? "");
  const body0 = proposalClarificationDraftBody(fullNotes) || fullNotes;
  const [draft, setDraft] = useState(body0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    setDraft(proposalClarificationDraftBody(fullNotes) || fullNotes);
    setError(null);
  }, [artifactId, version, fullNotes]);

  if (!content.notes && !canEdit) return null;

  const save = async () => {
    if (!onSave || !canEdit || busy) return;
    setBusy(true);
    setError(null);
    const m = fullNotes.match(/^(.+?\s+before send:\s*)/is);
    const notes = m ? `${m[1]}${draft.trim()}` : draft.trim() || fullNotes;
    try {
      await onSave(artifactId, version, { ...baseContent, notes });
      setSaved(true);
      window.setTimeout(() => setSaved(false), 2000);
    } catch (e) {
      const detail =
        e instanceof ApiProblemError
          ? e.problem.detail || e.problem.title
          : e instanceof Error
            ? e.message
            : String(e);
      setError(detail);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className={styles.clarificationDraft}>
      <span className={styles.docLabel}>{proposalClarificationDraftLabel(content)}</span>
      {canEdit ? (
        <>
          <p className={styles.composerEditHint}>
            Edit the outbound answer below, save, then approve send in the thread.
          </p>
          <textarea
            className={styles.composerTextarea}
            value={draft}
            rows={8}
            onChange={(e) => setDraft(e.target.value)}
          />
          <div className={styles.composerActions}>
            <Button
              type="button"
              variant="primary"
              size="workspace"
              disabledReason={busy ? "Saving" : undefined}
              onClick={() => void save()}
            >
              {busy ? "Saving…" : "Save draft answer"}
            </Button>
            {saved ? <span className={styles.composerSaved}>Saved</span> : null}
            {error ? <span className={styles.composerError}>{error}</span> : null}
          </div>
        </>
      ) : (
        <p className={styles.draftAnswerNote}>{body0 || "—"}</p>
      )}
    </div>
  );
}
