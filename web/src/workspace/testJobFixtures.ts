import type { components } from "../api/schema";

/** Opaque workflow id for workspace unit tests (not a pack workflow name). */
export const TEST_WORKFLOW = "wf_unit_demo";

export const TEST_SEAT = "seat_fixture";

/** Required snapshot fields added for colleague-aware chat UI. */
export const TEST_SNAPSHOT_SHELL: Pick<
  components["schemas"]["InstanceSnapshot"],
  "seat" | "assignee"
> = {
  seat: TEST_SEAT,
  assignee: { seat: TEST_SEAT, colleague_name: "Alex Doe", title: "Colleague" },
};

/** Build a pack artifact type id for tests without embedding pack names in source. */
export function testArtifactType(segment: string, suffix: string): string {
  return `${segment}_${suffix}`;
}
