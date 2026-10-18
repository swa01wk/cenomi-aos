/** Post-sign-in routes from docs/specs/trace-map.md (Sign-in). */
export function workspaceLandingPath(): string {
  return "/workspace";
}

export function consoleLandingPath(roles: string[]): string {
  const isRisk = roles.includes("risk");
  const isAdmin = roles.includes("platform_admin");
  if (isRisk && !isAdmin) return "/console/audit";
  return "/console/packs";
}

export function landingPathAfterSignIn(consoleUser: boolean, roles: string[]): string {
  return consoleUser ? consoleLandingPath(roles) : workspaceLandingPath();
}

/** After sign-in, honour a deep link saved in router state when present. */
export function postSignInPath(from: string | undefined, consoleUser: boolean, roles: string[]): string {
  const landing = landingPathAfterSignIn(consoleUser, roles);
  if (!from || from === "/") return landing;
  if (!consoleUser && from.startsWith("/console")) return landing;
  return from;
}
