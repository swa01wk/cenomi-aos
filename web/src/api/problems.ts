import type { components } from "./schema";

export type Problem = components["schemas"]["problem.schema"];

export class ApiProblemError extends Error {
  constructor(public readonly problem: Problem) {
    super(problem.detail ?? problem.title);
    this.name = "ApiProblemError";
  }
}

export function isProblem(value: unknown): value is Problem {
  if (!value || typeof value !== "object") return false;
  const p = value as Record<string, unknown>;
  return typeof p.code === "string" && typeof p.status === "number" && typeof p.title === "string";
}

export async function parseProblem(response: Response): Promise<Problem | null> {
  const type = response.headers.get("content-type") ?? "";
  if (!type.includes("problem+json") && !type.includes("application/json")) return null;
  try {
    const body: unknown = await response.clone().json();
    return isProblem(body) ? body : null;
  } catch {
    return null;
  }
}

export function problemMessage(problem: Problem): string {
  return problem.detail ?? problem.title;
}
