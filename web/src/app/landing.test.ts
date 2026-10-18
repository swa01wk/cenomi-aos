import { describe, expect, it } from "vitest";
import { consoleLandingPath, landingPathAfterSignIn, workspaceLandingPath } from "./landing";

describe("post-sign-in landing", () => {
  it("sends workspace people to /workspace", () => {
    expect(workspaceLandingPath()).toBe("/workspace");
    expect(landingPathAfterSignIn(false, ["requester"])).toBe("/workspace");
  });

  it("sends risk-only console people to audit", () => {
    expect(consoleLandingPath(["risk"])).toBe("/console/audit");
    expect(landingPathAfterSignIn(true, ["risk"])).toBe("/console/audit");
  });

  it("sends other console people to packs", () => {
    expect(consoleLandingPath(["platform_admin"])).toBe("/console/packs");
    expect(consoleLandingPath(["process_owner"])).toBe("/console/packs");
    expect(consoleLandingPath(["risk", "platform_admin"])).toBe("/console/packs");
    expect(landingPathAfterSignIn(true, ["seat_owner"])).toBe("/console/packs");
  });
});
