import { useQueries } from "@tanstack/react-query";
import { client } from "../../../api/client";
import { Skeleton } from "../../../components";
import { workspaceKeys } from "../../useWorkspaceQueries";
import type { InstanceSnapshot } from "../jobStreamReducer";
import { FieldListView } from "./FieldListView";
import styles from "./views.module.css";

type Props = {
  snapshot: InstanceSnapshot;
};

export function SupplierQuotesView({ snapshot }: Props) {
  const quotes = snapshot.artifacts.filter(
    (a) => a.artifact_type === "quote" && a.latest_version >= 1,
  );
  const rfqSuppliers = snapshot.artifacts
    .filter((a) => a.artifact_type === "rfq_email" && a.key)
    .map((a) => a.key);

  const queries = useQueries({
    queries: quotes.map((q) => ({
      queryKey: workspaceKeys.artifactVersion(q.artifact_id, q.latest_version),
      queryFn: async () => {
        const { data, error } = await client.GET("/artifacts/{id}/versions/{version}", {
          params: { path: { id: q.artifact_id, version: q.latest_version } },
        });
        if (error) throw error;
        return data!;
      },
    })),
  });

  const quotedKeys = new Set(quotes.map((q) => q.key || q.name));

  if (!quotes.length && !rfqSuppliers.length) {
    return <p className={styles.hiddenNote}>No supplier quotes yet.</p>;
  }

  return (
    <div className={styles.viewBody}>
      {quotes.map((meta, i) => {
        const detail = queries[i];
        const label = meta.key ? `Supplier ${meta.key}` : meta.name;
        return (
          <section key={meta.artifact_id} aria-label={label} className={styles.quoteStackSection}>
            <h3 className={styles.quoteStackHeading}>{label}</h3>
            {detail.isLoading && <Skeleton />}
            {detail.data ? <FieldListView view={meta.view} version={detail.data} /> : null}
            {detail.isError ? (
              <p className={styles.hiddenNote}>Could not load this quote — try the individual tab.</p>
            ) : null}
          </section>
        );
      })}
      {rfqSuppliers
        .filter((sid) => !quotedKeys.has(sid) && !quotes.some((q) => q.key === sid))
        .map((sid) => (
          <section key={sid} className={styles.quoteStackSection} aria-label={`Supplier ${sid}`}>
            <h3 className={styles.quoteStackHeading}>Supplier {sid}</h3>
            <p className={styles.hiddenNote}>
              Reply received or pending — open the RFQ email tab for this supplier, or reload after the worker
              captures the quote.
            </p>
          </section>
        ))}
    </div>
  );
}
