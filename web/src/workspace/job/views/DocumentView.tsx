import type { components } from "../../../api/schema";
import { formatFieldValue } from "./formatFieldValue";
import styles from "./views.module.css";

type ArtifactView = components["schemas"]["ArtifactView"];
type ArtifactVersion = components["schemas"]["ArtifactVersion"];
type FieldDef = ArtifactView["fields"][number];

const WIDE_TYPES = new Set<FieldDef["type"]>(["text", "list", "object"]);

/** view: document. Fields, labels and order come from the view; no field name is treated specially. Long text and
 *  lists get a full-width section; short fields sit two to a row. */
export function DocumentView({ view, version }: { view: ArtifactView; version: ArtifactVersion }) {
  const order = view.columns?.length ? view.columns : view.fields.map((f) => f.name);
  const byName = new Map(view.fields.map((f) => [f.name, f]));
  const fields = order.map((n) => byName.get(n)).filter((f): f is FieldDef => Boolean(f));

  return (
    <div className={styles.viewBody}>
      {version.hidden_fields.length > 0 && (
        <p className={styles.hiddenNote}>Some fields aren&apos;t shared with your role</p>
      )}
      <dl className={styles.docGrid}>
        {fields.map((field) => {
          const raw: unknown = version.content[field.name];
          const empty = raw == null || raw === "" || (Array.isArray(raw) && raw.length === 0);
          const wide = WIDE_TYPES.has(field.type);
          return (
            <div key={field.name} className={wide ? styles.docWide : styles.docField}>
              <dt className={styles.docLabel}>{field.label}</dt>
              <dd className={empty ? styles.docValueEmpty : styles.docValue}>
                {empty ? "Not set yet" : <FieldValue field={field} value={raw} />}
              </dd>
            </div>
          );
        })}
      </dl>
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
