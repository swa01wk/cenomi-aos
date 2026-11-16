import type { components } from "../../../api/schema";
import { formatFieldValue, formatLineItemObject } from "./formatFieldValue";
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
  if (!view || !version) return null;

  const fieldDefs = view.fields ?? [];
  const order = view.columns?.length ? view.columns : fieldDefs.map((f) => f.name);
  const byName = new Map(fieldDefs.map((f) => [f.name, f]));
  const hiddenFields = version.hidden_fields ?? [];

  const rawContent = (version.content ?? {}) as Record<string, unknown>;
  const showInboundPreview =
    version.artifact_type === "quote" || version.artifact_type === "proposal";
  const excerpt = showInboundPreview ? rawContent.reply_excerpt : undefined;
  const excerptText =
    typeof excerpt === "string" && excerpt.trim().length > 0 ? excerpt.trim() : null;

  return (
    <div className={styles.viewBody}>
      {excerptText && (
        <section aria-label="Inbound reply preview" className={styles.replyPreview}>
          <div className={styles.replyPreviewLabel}>Inbound reply</div>
          <pre className={styles.replyPreviewBody}>{excerptText}</pre>
        </section>
      )}
      {hiddenFields.length > 0 && (
        <p className={styles.hiddenNote}>Some fields aren&apos;t shared with your role</p>
      )}
      <dl className={styles.fieldGrid}>
        {order.map((name) => {
          const field = byName.get(name);
          if (!field) return null;
          if (name === "reply_excerpt" && excerptText) return null;
          const raw = rawContent[name];
          const lineObjects =
            field.type === "list" &&
            Array.isArray(raw) &&
            raw.length > 0 &&
            raw.every((item) => item !== null && typeof item === "object" && !Array.isArray(item));
          if (lineObjects) {
            return (
              <div key={name} className={styles.fieldRow}>
                <dt>
                  {field.label === "Lines"
                    ? "Order lines"
                    : field.name === "pricing_modules"
                      ? "Module pricing"
                      : field.name === "pricing_lines"
                        ? "Line pricing"
                        : field.label}
                </dt>
                <dd>
                  <ul className={styles.orderLines}>
                    {(raw as Record<string, unknown>[]).map((line, i) => (
                      <li key={i}>{formatLineItemObject(line)}</li>
                    ))}
                  </ul>
                </dd>
              </div>
            );
          }
          const { text } = formatFieldValue(field, raw);
          if (field.type === "text") {
            return (
              <div key={name} className={styles.fieldBlock}>
                <div className={styles.docLabel}>{field.label}</div>
                <div className={text === "—" ? styles.docValueEmpty : styles.docValue}>{text}</div>
              </div>
            );
          }
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
