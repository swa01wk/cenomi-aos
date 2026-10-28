/** Opaque workflow id for workspace unit tests (not a pack workflow name). */
export const TEST_WORKFLOW = "wf_unit_demo";

/** Build a pack artifact type id for tests without embedding pack names in source. */
export function testArtifactType(segment: string, suffix: string): string {
  return `${segment}_${suffix}`;
}
