import { describe, expect, it } from "vitest";
import { usdAmount } from "./ui";

describe("usdAmount", () => {
  it("shows cents", () => {
    expect(usdAmount(0)).toBe("0.00");
    expect(usdAmount(0.013)).toBe("0.01");
    expect(usdAmount(20)).toBe("20.00");
  });

  it("does not round a spend under a cent down to zero", () => {
    expect(usdAmount(0.004)).toBe("< 0.01");
  });
});
