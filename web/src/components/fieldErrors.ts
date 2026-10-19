import type { Problem } from "../api/problems";

/** Map JSON Pointer `/content/field_name` → `field_name` for form fields. */
export function pointerToFieldName(pointer: string): string {
  const parts = pointer.split("/").filter(Boolean);
  return parts[parts.length - 1] ?? pointer;
}

export function fieldErrorsFromProblem(problem: Problem): Map<string, string> {
  const map = new Map<string, string>();
  if (problem.code !== "validation_failed" || !problem.errors) return map;
  for (const err of problem.errors) {
    map.set(pointerToFieldName(err.pointer), err.message);
  }
  return map;
}
