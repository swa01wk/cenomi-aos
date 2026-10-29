import { describe, expect, it } from "vitest";
import { repeatOrderFirstMessage } from "./repeatOrder";

describe("repeatOrderFirstMessage", () => {
  it("includes source id and user note", () => {
    const msg = repeatOrderFirstMessage("QQ-0001", "Need delivery by Friday");
    expect(msg).toContain("QQ-0001");
    expect(msg).toContain("Need delivery by Friday");
  });

  it("works with an empty note", () => {
    expect(repeatOrderFirstMessage("QQ-0002", "")).toContain("QQ-0002");
  });
});
