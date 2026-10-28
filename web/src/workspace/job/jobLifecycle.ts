import type { Stage } from "../../components/types";
import type { InstanceSnapshot } from "./jobStreamReducer";

export function isJobClosed(snapshot: Pick<InstanceSnapshot, "state">): boolean {
  return snapshot.state === "closed";
}

/** Progress bar: every stage done when the workflow has finished. */
export function stagesForDisplay(stages: Stage[], workflowState: string): Stage[] {
  if (workflowState !== "closed") return stages;
  return stages.map((s) => ({ ...s, status: "done" as const }));
}

/** Header badge when the job lifecycle has ended. */
export function jobHeaderBadge(stages: Stage[], workflowState: string): string | null {
  if (workflowState === "closed") {
    const n = stages.length;
    return n > 0 ? `Complete · all ${n} stages done` : "Complete";
  }
  const index = stages.findIndex((s) => s.status === "current");
  if (index < 0) return null;
  return `${stages[index]!.label} · stage ${index + 1} of ${stages.length}`;
}

export const closedComposerMessage =
  "This job is complete. Start a new job from the sidebar if you need another quote.";
