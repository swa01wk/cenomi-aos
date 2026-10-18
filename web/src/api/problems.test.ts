import { describe, expect, it } from "vitest";
import { isProblem, parseProblem, problemMessage } from "./problems";

describe("parseProblem", () => {
  it("reads application/problem+json", async () => {
    const body = {
      type: "https://aos.local/problems/stale_version",
      title: "Someone else changed this",
      status: 409,
      code: "stale_version",
      detail: "Reload and try again.",
      decision_id: "dec-1",
      rule: "example_rule",
    };
    const res = new Response(JSON.stringify(body), {
      status: 409,
      headers: { "content-type": "application/problem+json" },
    });
    const problem = await parseProblem(res);
    expect(problem?.code).toBe("stale_version");
    expect(problem?.status).toBe(409);
    expect(problem?.detail).toBe("Reload and try again.");
    expect(problem?.decision_id).toBe("dec-1");
    expect(problem?.rule).toBe("example_rule");
    expect(problemMessage(problem!)).toBe("Reload and try again.");
  });

  it("returns null for non-JSON", async () => {
    const res = new Response("nope", { status: 500 });
    expect(await parseProblem(res)).toBeNull();
  });

  it("isProblem rejects partial objects", () => {
    expect(isProblem({ code: "internal" })).toBe(false);
    expect(isProblem({ code: "internal", status: 500, title: "Error" })).toBe(true);
  });
});
