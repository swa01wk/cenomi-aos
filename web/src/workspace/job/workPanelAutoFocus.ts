import type { InstanceSnapshot } from "./jobStreamReducer";
import { SUPPLIER_QUOTES_TAB_ID } from "./workPanelConstants";

/** Preferred artifact view types by workflow state (first match wins). */
const STAGE_VIEW_PRIORITY: Record<string, string[]> = {
  conversation: ["document"],
  intake: ["document"],
  shortlisting: ["sheet", "document"],
  rfq_drafting: ["message_composer", "sheet", "document"],
  rfq_sending: ["message_composer", "sheet", "document"],
  awaiting_quotes: ["tracker", "message_composer", "sheet"],
  comparison: ["comparison", "tracker", "sheet"],
  ordering: ["record_preview", "comparison", "tracker"],
  closed: ["record_preview", "comparison", "tracker", "document"],
  master_rfp_drafting: ["document", "sheet"],
  rfp_invitation_drafting: ["message_composer", "document", "sheet"],
  rfp_sending: ["message_composer", "document", "sheet"],
  awaiting_proposals: ["tracker", "message_composer", "sheet"],
};

function artifactIdForView(snapshot: InstanceSnapshot, viewType: string): string | null {
  if (viewType === "tracker") {
    const quotes = snapshot.artifacts.filter(
      (a) => a.artifact_type === "quote" && a.latest_version >= 1,
    );
    if (
      quotes.length >= 1 &&
      (snapshot.state === "awaiting_quotes" ||
        snapshot.state === "comparison" ||
        snapshot.state === "awaiting_proposals" ||
        snapshot.state === "closed")
    ) {
      return SUPPLIER_QUOTES_TAB_ID;
    }
  }
  const row = snapshot.artifacts.find(
    (a) => a.view?.type === viewType && a.latest_version >= 1,
  );
  if (row) return row.artifact_id;
  if (viewType === "document") {
    if (snapshot.state === "master_rfp_drafting") {
      const master = snapshot.artifacts.find(
        (a) => a.artifact_type === "master_rfp" && a.latest_version >= 1,
      );
      if (master) return master.artifact_id;
    }
    const brief = snapshot.artifacts.find(
      (a) => a.artifact_type === "brief" && a.latest_version >= 1,
    );
    return brief?.artifact_id ?? null;
  }
  return null;
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

function effectivePanelArtifactId(
  snapshot: InstanceSnapshot,
  currentPanelId: string | null,
): string | null {
  if (!currentPanelId || currentPanelId === "work") return null;
  return snapshot.artifacts.some((a) => a.artifact_id === currentPanelId) ? currentPanelId : null;
}

export function shouldAutoFocusWorkPanel(
  snapshot: InstanceSnapshot,
  currentPanelId: string | null,
  userOverrodePanel: boolean,
): string | null {
  const target = recommendedWorkPanelArtifactId(snapshot);
  if (!target) return null;
  const effectivePanelId = effectivePanelArtifactId(snapshot, currentPanelId);
  if (target === effectivePanelId) return null;
  if (userOverrodePanel) return null;

  const current = effectivePanelId
    ? snapshot.artifacts.find((a) => a.artifact_id === effectivePanelId)
    : undefined;
  const order = STAGE_VIEW_PRIORITY[snapshot.state] ?? [];
  const targetType = snapshot.artifacts.find((a) => a.artifact_id === target)?.view?.type;
  const currentType = current?.view?.type;

  if (!effectivePanelId || !currentType) return target;

  const targetRank = targetType ? order.indexOf(targetType) : -1;
  const currentRank = currentType ? order.indexOf(currentType) : -1;
  if (targetRank >= 0 && (currentRank < 0 || targetRank < currentRank)) return target;

  if (snapshot.state === "shortlisting" && targetType === "sheet" && currentType === "document") {
    return target;
  }

  return null;
}
