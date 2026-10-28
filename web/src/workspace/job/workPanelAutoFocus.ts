import type { InstanceSnapshot } from "./jobStreamReducer";

/** Preferred work-panel document types by workflow state (first match wins). */
const STAGE_ARTIFACT_PRIORITY: Record<string, string[]> = {
  intake: ["brief"],
  shortlisting: ["supplier_list", "brief"],
  rfq_drafting: ["rfq_email", "supplier_list", "brief"],
  rfq_sending: ["rfq_email", "supplier_list", "brief"],
  awaiting_quotes: ["quote", "rfq_email", "supplier_list"],
  comparison: ["comparison", "quote", "supplier_list"],
  ordering: ["po_payload", "comparison", "quote"],
  closed: ["po_payload", "comparison", "quote", "brief"],
};

function artifactIdForType(snapshot: InstanceSnapshot, artifactType: string): string | null {
  const row = snapshot.artifacts.find(
    (a) => a.artifact_type === artifactType && a.latest_version >= 1,
  );
  return row?.artifact_id ?? null;
}

/** Which artifact tab the work panel should show for this stage (null = keep current default). */
export function recommendedWorkPanelArtifactId(snapshot: InstanceSnapshot): string | null {
  const order = STAGE_ARTIFACT_PRIORITY[snapshot.state];
  if (!order?.length) return null;
  for (const type of order) {
    const id = artifactIdForType(snapshot, type);
    if (id) return id;
  }
  return null;
}

export function shouldAutoFocusWorkPanel(
  snapshot: InstanceSnapshot,
  currentPanelId: string | null,
  userOverrodePanel: boolean,
): string | null {
  const target = recommendedWorkPanelArtifactId(snapshot);
  if (!target) return null;
  if (target === currentPanelId) return null;
  if (userOverrodePanel && currentPanelId) return null;

  const current = currentPanelId
    ? snapshot.artifacts.find((a) => a.artifact_id === currentPanelId)
    : undefined;
  const order = STAGE_ARTIFACT_PRIORITY[snapshot.state] ?? [];
  const targetType = snapshot.artifacts.find((a) => a.artifact_id === target)?.artifact_type;
  const currentType = current?.artifact_type;

  if (!currentPanelId || !currentType) return target;

  const targetRank = targetType ? order.indexOf(targetType) : -1;
  const currentRank = order.indexOf(currentType);
  if (targetRank >= 0 && (currentRank < 0 || targetRank < currentRank)) return target;

  if (snapshot.state === "shortlisting" && targetType === "supplier_list" && currentType === "brief") {
    return target;
  }

  return null;
}
