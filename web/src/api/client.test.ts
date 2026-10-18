import { beforeEach, describe, expect, it, vi } from "vitest";
import { handleUnauthorized, setUnauthorizedHandler } from "./client";
import { ApiProblemError } from "./problems";
import { clearToken, getToken, saveToken } from "./session";

describe("401 handling", () => {
  beforeEach(() => {
    clearToken();
  });

  it("clears the token and runs the unauthorized handler", () => {
    saveToken("secret");
    const handler = vi.fn();
    setUnauthorizedHandler(handler);

    expect(() =>
      handleUnauthorized({
        type: "about:blank",
        title: "Sign in",
        status: 401,
        code: "unauthenticated",
      }),
    ).toThrow(ApiProblemError);

    expect(getToken()).toBeNull();
    expect(handler).toHaveBeenCalled();
  });
});
