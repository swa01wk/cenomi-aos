import { describe, expect, it } from "vitest";
import { postSignInPath } from "./landing";

describe("deep link return path", () => {
  it("prefers saved from path over role landing", () => {
    expect(postSignInPath("/console/org", true, ["platform_admin"])).toBe("/console/org");
  });

  it("falls back to role landing when no from path", () => {
    expect(postSignInPath(undefined, false, ["requester"])).toBe("/workspace");
  });

  it("ignores console deep links for workspace-only accounts", () => {
    expect(postSignInPath("/console/packs", false, ["sourcing_user"])).toBe("/workspace");
    expect(postSignInPath("/console/audit?tab=1", false, ["end_user"])).toBe("/workspace");
  });
});
