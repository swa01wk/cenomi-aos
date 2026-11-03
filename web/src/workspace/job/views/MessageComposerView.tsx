import { useEffect, useState } from "react";
import { Button } from "../../../components";
import { ApiProblemError } from "../../../api/problems";
import type { ArtifactViewComponentProps } from "./index";
import styles from "./views.module.css";

export function MessageComposerView({
  version,
  artifactId,
  artifactStatus,
  latestVersion,
  canEdit,
  onSave,
}: ArtifactViewComponentProps) {
  const raw = version.content as Record<string, unknown>;
  const to = String(raw.to ?? "");
  const subject0 = String(raw.subject ?? "");
  const body0 = String(raw.body ?? "");

  const [subject, setSubject] = useState(subject0);
  const [body, setBody] = useState(body0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [savedFlash, setSavedFlash] = useState(false);

  useEffect(() => {
    setSubject(subject0);
    setBody(body0);
    setError(null);
  }, [artifactId, version.version, subject0, body0]);

  const isLatest = latestVersion != null && version.version === latestVersion;
  const editable = Boolean(canEdit && isLatest && onSave);
  const dirty = editable && (subject !== subject0 || body !== body0);

  const save = async () => {
    if (!onSave || !editable || busy) return;
    setBusy(true);
    setError(null);
    try {
      const next = { ...raw, subject: subject.trim(), body: body.trim() };
      await onSave(next);
      setSavedFlash(true);
      window.setTimeout(() => setSavedFlash(false), 2500);
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
    <div className={styles.composerView}>
      {editable ? (
        <p className={styles.composerEditHint}>
          Edit the draft below, then save. Your version is what goes out on approve and send.
        </p>
      ) : !isLatest ? (
        <p className={styles.composerEditHint}>Older version — switch to the latest to edit.</p>
      ) : artifactStatus === "final" || artifactStatus === "locked" ? (
        <p className={styles.composerEditHint}>Sent — this draft is locked and cannot be edited.</p>
      ) : null}
      <label className={styles.composerField}>
        <span className={styles.composerLabel}>To</span>
        <input className={styles.composerInput} type="text" value={to} readOnly aria-readonly />
      </label>
      <label className={styles.composerField}>
        <span className={styles.composerLabel}>Subject</span>
        <input
          className={styles.composerInput}
          type="text"
          value={subject}
          readOnly={!editable}
          onChange={(e) => setSubject(e.target.value)}
        />
      </label>
      <label className={styles.composerField}>
        <span className={styles.composerLabel}>Body</span>
        <textarea
          className={styles.composerTextarea}
          value={body}
          readOnly={!editable}
          rows={22}
          onChange={(e) => setBody(e.target.value)}
        />
      </label>
      {editable ? (
        <div className={styles.composerActions}>
          <Button
            type="button"
            variant="primary"
            size="workspace"
            disabledReason={busy ? "Saving" : !dirty ? "No changes to save" : undefined}
            onClick={() => void save()}
          >
            {busy ? "Saving…" : "Save draft"}
          </Button>
          {savedFlash ? <span className={styles.composerSaved}>Saved</span> : null}
          {error ? <span className={styles.composerError}>{error}</span> : null}
        </div>
      ) : null}
    </div>
  );
}
