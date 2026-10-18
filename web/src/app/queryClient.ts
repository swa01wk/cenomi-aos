import { QueryClient } from "@tanstack/react-query";
import { ApiProblemError } from "../api/problems";

function shouldRetryQuery(failureCount: number, error: unknown): boolean {
  if (error instanceof ApiProblemError) {
    const s = error.problem.status;
    if (s >= 400 && s < 500) return false;
  }
  return failureCount < 1;
}

export function createAppQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: shouldRetryQuery },
      mutations: { retry: false },
    },
  });
}
