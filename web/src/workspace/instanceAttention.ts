import type { components } from "../api/schema";

type InstanceSummary = components["schemas"]["InstanceSummary"];

/** Open pending (decision) assigned to this person. */
export function jobNeedsViewerAction(job: InstanceSummary, viewerPersonId: string): boolean {
  return job.waiting_on?.kind === "person" && job.waiting_on.person_id === viewerPersonId;
}

export function pendingActionLabel(job: InstanceSummary): string {
  const label = job.waiting_on?.label?.trim();
  return label || "Needs your action";
}

/** Needs-action first, then newest activity. */
export function sortJobsForViewer(jobs: InstanceSummary[], viewerPersonId: string): InstanceSummary[] {
  return [...jobs].sort((a, b) => {
    const aNeeds = jobNeedsViewerAction(a, viewerPersonId);
    const bNeeds = jobNeedsViewerAction(b, viewerPersonId);
    if (aNeeds !== bNeeds) return aNeeds ? -1 : 1;
    const aAt = a.last_activity_at ?? a.started_at ?? "";
    const bAt = b.last_activity_at ?? b.started_at ?? "";
    return bAt.localeCompare(aAt);
  });
}

export function countJobsNeedingViewer(jobs: InstanceSummary[] | undefined, viewerPersonId: string): number {
  if (!jobs?.length) return 0;
  return jobs.filter((j) => jobNeedsViewerAction(j, viewerPersonId)).length;
}
