import { beforeEach, describe, expect, it, vi } from "vitest";
import { handleUnauthorized, setUnauthorizedHandler } from "./client";
import { ApiProblemError } from "./problems";
import { clearToken, getToken, saveToken } from "./session";

describe("401 handling", () => {
  beforeEach(() => {
    clearToken();
  });

  it("runs the unauthorized handler (session layer clears the token)", () => {
    saveToken("secret");
    const handler = vi.fn(() => clearToken());
    setUnauthorizedHandler(handler);

    expect(() =>
      handleUnauthorized({
        type: "about:blank",
        title: "Sign in",
        status: 401,
        code: "unauthenticated",
      }),
    ).toThrow(ApiProblemError);

    expect(handler).toHaveBeenCalled();
    expect(getToken()).toBeNull();
  });
});
