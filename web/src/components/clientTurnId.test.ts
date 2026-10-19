import { afterEach, describe, expect, it, vi } from "vitest";
import { newClientTurnId } from "./clientTurnId";

describe("newClientTurnId", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("uses randomUUID when present", () => {
    vi.stubGlobal("crypto", { randomUUID: () => "11111111-1111-4111-8111-111111111111" });
    expect(newClientTurnId()).toBe("11111111-1111-4111-8111-111111111111");
  });

  it("falls back to getRandomValues", () => {
    const bytes = new Uint8Array(16);
    for (let i = 0; i < 16; i++) bytes[i] = i;
    vi.stubGlobal("crypto", {
      getRandomValues: (arr: Uint8Array) => {
        arr.set(bytes);
        return arr;
      },
    });
    const id = newClientTurnId();
    expect(id).toMatch(/^[0-9a-f-]{36}$/);
  });
});
