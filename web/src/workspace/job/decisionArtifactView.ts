import type { components } from "../../api/schema";

type PendingItem = components["schemas"]["PendingItem"];
type ArtifactView = components["schemas"]["ArtifactView"];
type ArtifactSummary = components["schemas"]["ArtifactSummary"];

/** View metadata for row selection when the snapshot summary omits row_key. */
export function decisionSelectionView(
  pending: Pick<PendingItem, "event" | "artifact_ref">,
  artifact?: Pick<ArtifactSummary, "view" | "artifact_type" | "latest_version">,
): ArtifactView | undefined {
  if (artifact?.view?.row_key) return artifact.view;
  if (pending.event === "decision.supplier_selected") {
    return {
      type: "sheet",
      row_key: "supplier",
      columns: ["rank", "supplier", "total", "score"],
      fields: [
        { name: "rank", label: "Rank", type: "integer" },
        { name: "supplier", label: "Vendor", type: "string" },
        { name: "total", label: "Quote total", type: "money" },
        { name: "score", label: "Score", type: "number" },
        { name: "lead_time_days", label: "Lead time (days)", type: "integer" },
      ],
    };
  }
  if (artifact?.view) return artifact.view;
  return undefined;
}

export function decisionSelectionVersion(
  pending: Pick<PendingItem, "artifact_ref">,
  artifact?: Pick<ArtifactSummary, "latest_version">,
): number {
  const pinned = pending.artifact_ref?.version;
  const latest = artifact?.latest_version;
  if (pinned != null && pinned > 0) return pinned;
  if (latest != null && latest > 0) return latest;
  return 1;
}
