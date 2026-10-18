import createClient, { type Middleware } from "openapi-fetch";
import type { paths } from "./schema";
import { ApiProblemError, parseProblem } from "./problems";
import { getToken } from "./session";

let onUnauthorized: () => void = () => {};

export function setUnauthorizedHandler(fn: () => void): void {
  onUnauthorized = fn;
}

/** Notifies the app (401 / unauthenticated); SessionProvider clears the token and navigates. */
export function handleUnauthorized(problem?: import("./problems").Problem): never {
  onUnauthorized();
  if (problem) throw new ApiProblemError(problem);
  throw new ApiProblemError({
    type: "about:blank",
    title: "Sign in required",
    status: 401,
    code: "unauthenticated",
  });
}

const middleware: Middleware = {
  onRequest({ request }) {
    const token = getToken();
    if (token) request.headers.set("Authorization", `Bearer ${token}`);
    return request;
  },
  async onResponse({ response }) {
    if (response.ok) return response;
    const problem = await parseProblem(response);
    if (response.status === 401) handleUnauthorized(problem ?? undefined);
    if (problem) throw new ApiProblemError(problem);
    throw new Error(`${response.status} ${response.statusText}`);
  },
};

function apiBaseUrl(): string {
  if (typeof window !== "undefined" && window.location?.origin && window.location.origin !== "null") {
    return `${window.location.origin}/api`;
  }
  return "/api";
}

export const client = createClient<paths>({
  baseUrl: apiBaseUrl(),
  fetch: (request) => globalThis.fetch(request),
});
client.use(middleware);
