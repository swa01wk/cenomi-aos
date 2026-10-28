import type { InstanceSnapshot } from "./jobStreamReducer";

/** Preferred artifact view types by workflow state (first match wins). */
const STAGE_VIEW_PRIORITY: Record<string, string[]> = {
  intake: ["document"],
  shortlisting: ["sheet", "document"],
  rfq_drafting: ["message_composer", "sheet", "document"],
  rfq_sending: ["message_composer", "sheet", "document"],
  awaiting_quotes: ["tracker", "message_composer", "sheet"],
  comparison: ["comparison", "tracker", "sheet"],
  ordering: ["record_preview", "comparison", "tracker"],
  closed: ["record_preview", "comparison", "tracker", "document"],
};

function artifactIdForView(snapshot: InstanceSnapshot, viewType: string): string | null {
  const row = snapshot.artifacts.find(
    (a) => a.view?.type === viewType && a.latest_version >= 1,
  );
  return row?.artifact_id ?? null;
}

/** Which artifact tab the work panel should show for this stage (null = keep current default). */
export function recommendedWorkPanelArtifactId(snapshot: InstanceSnapshot): string | null {
  const order = STAGE_VIEW_PRIORITY[snapshot.state];
  if (!order?.length) return null;
  for (const viewType of order) {
    const id = artifactIdForView(snapshot, viewType);
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
  const order = STAGE_VIEW_PRIORITY[snapshot.state] ?? [];
  const targetType = snapshot.artifacts.find((a) => a.artifact_id === target)?.view?.type;
  const currentType = current?.view?.type;

  if (!currentPanelId || !currentType) return target;

  const targetRank = targetType ? order.indexOf(targetType) : -1;
  const currentRank = currentType ? order.indexOf(currentType) : -1;
  if (targetRank >= 0 && (currentRank < 0 || targetRank < currentRank)) return target;

  if (snapshot.state === "shortlisting" && targetType === "sheet" && currentType === "document") {
    return target;
  }

  return null;
}
