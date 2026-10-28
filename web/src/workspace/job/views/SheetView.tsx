import { DataTable } from "../../../components";
import type { components } from "../../../api/schema";
import { formatFieldValue } from "./formatFieldValue";
import styles from "./views.module.css";

type ArtifactView = components["schemas"]["ArtifactView"];
type ArtifactVersion = components["schemas"]["ArtifactVersion"];

export function SheetView({
  view,
  version,
}: {
  view: ArtifactView;
  version: ArtifactVersion;
}) {
  const content = version.content as { rows?: unknown };
  const rows = Array.isArray(content.rows) ? (content.rows as Record<string, unknown>[]) : [];
  const order = view.columns?.length ? view.columns : view.fields.map((f) => f.name);
  const byName = new Map(view.fields.map((f) => [f.name, f]));
  const rowKey = view.row_key;

  return (
    <div className={styles.viewBody}>
      {version.hidden_fields.length > 0 && (
        <p className={styles.hiddenNote}>Some fields aren&apos;t shared with your role</p>
      )}
      <DataTable
        caption={view.type}
        rows={rows}
        empty={<p className={styles.hiddenNote}>No rows yet</p>}
        getRowKey={(row) => {
          const key = rowKey ? row[rowKey] : undefined;
          if (key != null && key !== "") return String(key);
          return order.map((name) => String(row[name] ?? "")).join("|");
        }}
        columns={order.flatMap((name) => {
          const field = byName.get(name);
          if (!field) return [];
          return [
            {
              id: name,
              header: field.label,
              align: field.type === "integer" || field.type === "number" || field.type === "money" ? ("right" as const) : ("left" as const),
              render: (row: Record<string, unknown>) => formatFieldValue(field, row[name]).text,
            },
          ];
        })}
      />
    </div>
  );
}
