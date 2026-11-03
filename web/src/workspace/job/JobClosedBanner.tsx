import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router";
import { client } from "../../api/client";
import { workspaceKeys } from "../useWorkspaceQueries";
import type { InstanceSnapshot } from "./jobStreamReducer";
import styles from "./JobClosedBanner.module.css";

function formatMoney(raw: unknown): string | null {
  if (raw == null) return null;
  if (typeof raw === "object" && raw !== null && "amount" in raw) {
    const amount = Number((raw as { amount?: unknown }).amount);
    const currency = String((raw as { currency?: unknown }).currency || "SAR");
    if (Number.isFinite(amount)) {
      try {
        return new Intl.NumberFormat(undefined, { style: "currency", currency }).format(amount);
      } catch {
        return `${currency} ${amount.toFixed(2)}`;
      }
    }
  }
  const n = typeof raw === "number" ? raw : Number(raw);
  if (Number.isFinite(n)) {
    return new Intl.NumberFormat(undefined, { style: "currency", currency: "SAR" }).format(n);
  }
  return null;
}

export function JobClosedBanner({ snapshot }: { snapshot: InstanceSnapshot }) {
  const poArtifact = snapshot.artifacts.find(
    (a) => a.artifact_type === "po_payload" && a.latest_version >= 1,
  );

  const poContent = useQuery({
    queryKey: workspaceKeys.artifactVersion(
      poArtifact?.artifact_id ?? "none",
      poArtifact?.latest_version ?? 0,
    ),
    enabled: Boolean(poArtifact?.artifact_id),
    queryFn: async () => {
      const { data, error } = await client.GET("/artifacts/{id}/versions/{version}", {
        params: {
          path: { id: poArtifact!.artifact_id, version: poArtifact!.latest_version },
        },
      });
      if (error) throw error;
      return data!.content as Record<string, unknown>;
    },
    staleTime: 60_000,
  });

  const reference = poContent.data?.reference
    ? String(poContent.data.reference)
    : poArtifact
      ? `PO-${snapshot.instance_id.replace(/\D/g, "").padStart(6, "0")}`
      : null;
  const supplierId = poContent.data?.supplier_id ? String(poContent.data.supplier_id) : null;
  const amount = formatMoney(poContent.data?.po_amount);

  return (
    <div className={styles.banner} role="status" aria-live="polite">
      <div className={styles.iconWrap} aria-hidden>
        <span className={styles.iconRing} />
        <span className={styles.icon}>✓</span>
      </div>
      <div className={styles.copy}>
        <p className={styles.title}>
          {reference ? "Order placed" : "Job complete"}
        </p>
        {reference ? (
          <>
            <p className={styles.poLine}>
              Purchase order{" "}
              <span className={styles.poId} data-testid="closed-po-id">
                {reference}
              </span>{" "}
              created in Oracle Fusion
              {supplierId ? (
                <>
                  {" "}
                  for <span className={styles.supplierId}>{supplierId}</span>
                </>
              ) : null}
              .
            </p>
            {amount ? <p className={styles.amount}>{amount} total</p> : null}
          </>
        ) : (
          <p className={styles.detail}>
            <span className={styles.jobId}>{snapshot.instance_id}</span> is closed. The purchase path finished — open
            documents on the right or scroll above for the full history.
          </p>
        )}
        <p className={styles.detailMuted}>
          <span className={styles.jobId}>{snapshot.instance_id}</span> is closed. PO details stay in the work panel.
        </p>
        <Link
          to={`/workspace?repeat=${encodeURIComponent(snapshot.instance_id)}`}
          className={styles.repeatLink}
        >
          Repeat this order
        </Link>
      </div>
    </div>
  );
}
