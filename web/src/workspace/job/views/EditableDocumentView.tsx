import { useEffect, useState } from "react";
import type { components } from "../../../api/schema";
import { Button } from "../../../components";
import { DocumentPdfDownload } from "./DocumentPdfDownload";
import { formatFieldValue } from "./formatFieldValue";
import styles from "./views.module.css";

type ArtifactView = components["schemas"]["ArtifactView"];
type ArtifactVersion = components["schemas"]["ArtifactVersion"];
type FieldDef = ArtifactView["fields"][number];

const WIDE_TYPES = new Set<FieldDef["type"]>(["text", "list", "object"]);
const EDITABLE_TYPES = new Set<FieldDef["type"]>(["text", "string"]);

export function EditableDocumentView({
  view,
  version,
  onSave,
  artifactType,
}: {
  view: ArtifactView;
  version: ArtifactVersion;
  onSave: (content: Record<string, unknown>) => Promise<void>;
  artifactType?: string;
}) {
  const order = view.columns?.length ? view.columns : view.fields.map((f) => f.name);
  const byName = new Map(view.fields.map((f) => [f.name, f]));
  const fields = order.map((n) => byName.get(n)).filter((f): f is FieldDef => Boolean(f));
  const hiddenFields = version.hidden_fields ?? [];
  const baseContent = (version.content ?? {}) as Record<string, unknown>;
  const editableNames = new Set(
    fields.filter((f) => EDITABLE_TYPES.has(f.type) && !hiddenFields.includes(f.name)).map((f) => f.name),
  );

  const [draft, setDraft] = useState<Record<string, unknown>>(() => ({ ...baseContent }));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setDraft({ ...baseContent });
    setError(null);
  }, [version.version, version.content]);

  const dirty = fields.some((f) => {
    if (!editableNames.has(f.name)) return false;
    return String(draft[f.name] ?? "") !== String(baseContent[f.name] ?? "");
  });

  const save = async () => {
    if (!dirty || busy) return;
    setBusy(true);
    setError(null);
    try {
      const next = { ...baseContent, ...draft };
      await onSave(next);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const type = artifactType ?? version.artifact_type;
  const pdfContent = { ...baseContent, ...draft };

  return (
    <div className={styles.viewBody}>
      {type === "master_rfp" ? (
        <DocumentPdfDownload view={view} content={pdfContent} artifactType={type} />
      ) : null}
      {hiddenFields.length > 0 && (
        <p className={styles.hiddenNote}>Some fields aren&apos;t shared with your role</p>
      )}
      <dl className={styles.docGrid}>
        {fields.map((field) => {
          const raw: unknown = baseContent[field.name];
          const empty = raw == null || raw === "" || (Array.isArray(raw) && raw.length === 0);
          const wide = WIDE_TYPES.has(field.type);
          const editable = editableNames.has(field.name);
          return (
            <div key={field.name} className={wide ? styles.docWide : styles.docField}>
              <dt className={styles.docLabel}>{field.label}</dt>
              <dd className={empty && !editable ? styles.docValueEmpty : styles.docValue}>
                {editable ? (
                  field.type === "text" ? (
                    <textarea
                      className={styles.docTextarea}
                      rows={Math.max(6, String(draft[field.name] ?? "").split("\n").length + 1)}
                      value={String(draft[field.name] ?? "")}
                      onChange={(e) => setDraft((d) => ({ ...d, [field.name]: e.target.value }))}
                    />
                  ) : (
                    <input
                      className={styles.docInput}
                      type="text"
                      value={String(draft[field.name] ?? "")}
                      onChange={(e) => setDraft((d) => ({ ...d, [field.name]: e.target.value }))}
                    />
                  )
                ) : empty ? (
                  "Not set yet"
                ) : (
                  <FieldValue field={field} value={raw} />
                )}
              </dd>
            </div>
          );
        })}
      </dl>
      {editableNames.size > 0 ? (
        <div className={styles.docEditActions}>
          {error ? <p className={styles.docEditError}>{error}</p> : null}
          <Button type="button" variant="primary" disabledReason={!dirty ? "No changes" : busy ? "Saving" : undefined} onClick={() => void save()}>
            {busy ? "Saving…" : "Save changes"}
          </Button>
        </div>
      ) : null}
    </div>
  );
}

function FieldValue({ field, value }: { field: FieldDef; value: unknown }) {
  if (field.type === "list" && Array.isArray(value)) {
    return (
      <ul className={styles.docList}>
        {value.map((item, i) => (
          <li key={i}>{typeof item === "string" ? item : JSON.stringify(item)}</li>
        ))}
      </ul>
    );
  }
  return <>{formatFieldValue(field, value).text}</>;
}
