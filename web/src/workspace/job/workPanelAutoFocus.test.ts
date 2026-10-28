import { describe, expect, it } from "vitest";
import { recommendedWorkPanelArtifactId, shouldAutoFocusWorkPanel } from "./workPanelAutoFocus";
import type { InstanceSnapshot } from "./jobStreamReducer";

function snap(partial: Partial<InstanceSnapshot>): InstanceSnapshot {
  return {
    instance_id: "QQ-1",
    title: "Test",
    workflow: "quick_quote",
    pack_version: "p@1",
    version: 1,
    state: "shortlisting",
    stages: [],
    participants: [],
    my_roles: ["buyer"],
    pending: [],
    turns: [],
    cursor: "0",
    artifacts: [],
    ...partial,
  } as InstanceSnapshot;
}

describe("workPanelAutoFocus", () => {
  it("prefers supplier list during shortlisting", () => {
    const id = recommendedWorkPanelArtifactId(
      snap({
        artifacts: [
          { artifact_id: "brief1", artifact_type: "brief", name: "Brief", latest_version: 2, status: "final", view: { type: "form", fields: [], columns: [] } },
          { artifact_id: "list1", artifact_type: "supplier_list", name: "Supplier List", latest_version: 9, status: "final", view: { type: "sheet", fields: [], columns: [] } },
        ],
      }),
    );
    expect(id).toBe("list1");
  });

  it("auto-switches from brief to supplier list when shortlisting", () => {
    const snapshot = snap({
      artifacts: [
        { artifact_id: "brief1", artifact_type: "brief", name: "Brief", latest_version: 2, status: "final", view: { type: "form", fields: [], columns: [] } },
        { artifact_id: "list1", artifact_type: "supplier_list", name: "Supplier List", latest_version: 9, status: "final", view: { type: "sheet", fields: [], columns: [] } },
      ],
    });
    expect(shouldAutoFocusWorkPanel(snapshot, "brief1", false)).toBe("list1");
    expect(shouldAutoFocusWorkPanel(snapshot, "list1", false)).toBeNull();
  });

  it("respects manual tab choice", () => {
    const snapshot = snap({
      artifacts: [
        { artifact_id: "brief1", artifact_type: "brief", name: "Brief", latest_version: 2, status: "final", view: { type: "form", fields: [], columns: [] } },
        { artifact_id: "list1", artifact_type: "supplier_list", name: "Supplier List", latest_version: 9, status: "final", view: { type: "sheet", fields: [], columns: [] } },
      ],
    });
    expect(shouldAutoFocusWorkPanel(snapshot, "brief1", true)).toBeNull();
  });
});
