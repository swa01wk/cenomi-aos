import { describe, expect, it } from "vitest";
import { hashRouteTarget } from "./HashRedirect";

describe("hashRouteTarget", () => {
  it("maps legacy hash paths to real routes", () => {
    expect(hashRouteTarget("#/console/packs")).toBe("/console/packs");
    expect(hashRouteTarget("#/workspace")).toBe("/workspace");
    expect(hashRouteTarget("#console/org")).toBe("/console/org");
  });

  it("ignores empty hashes", () => {
    expect(hashRouteTarget("#")).toBeNull();
    expect(hashRouteTarget("")).toBeNull();
  });
});
