import type { components } from "../../../api/schema";
import { formatFieldValue } from "./formatFieldValue";
import styles from "./views.module.css";

type ArtifactView = components["schemas"]["ArtifactView"];
type ArtifactVersion = components["schemas"]["ArtifactVersion"];

export function FieldListView({
  view,
  version,
}: {
  view: ArtifactView;
  version: ArtifactVersion;
}) {
  const order = view.columns?.length ? view.columns : view.fields.map((f) => f.name);
  const byName = new Map(view.fields.map((f) => [f.name, f]));

  return (
    <div className={styles.viewBody}>
      {version.hidden_fields.length > 0 && (
        <p className={styles.hiddenNote}>Some fields aren&apos;t shared with your role</p>
      )}
      <dl className={styles.fieldGrid}>
        {order.map((name) => {
          const field = byName.get(name);
          if (!field) return null;
          const raw = version.content[name];
          // Right-aligning numbers is for row views (sheet, tracker); in a label/value list they stay under their label.
          const { text } = formatFieldValue(field, raw);
          return (
            <div key={name} className={styles.fieldRow}>
              <dt>{field.label}</dt>
              <dd>{text}</dd>
            </div>
          );
        })}
      </dl>
    </div>
  );
}
