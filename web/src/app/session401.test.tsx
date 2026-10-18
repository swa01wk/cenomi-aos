import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { createMemoryRouter, Outlet, RouterProvider } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

const meState = vi.hoisted(() => ({ calls: 0 }));

vi.hoisted(() => {
  const toUrl = (input: RequestInfo | URL): string => {
    if (typeof input === "string") {
      return input.startsWith("http") ? input : `http://localhost${input.startsWith("/") ? input : `/${input}`}`;
    }
    if (input instanceof URL) return input.href;
    const raw = input instanceof Request ? input.url : String(input);
    return raw.startsWith("http") ? raw : `http://localhost${raw.startsWith("/") ? raw : `/${raw}`}`;
  };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = toUrl(input);
      if (url.includes("/me")) {
        meState.calls += 1;
        return Response.json(
          {
            type: "about:blank",
            title: "Sign in required",
            status: 401,
            code: "unauthenticated",
          },
          { status: 401, headers: { "content-type": "application/problem+json" } },
        );
      }
      return Response.json({}, { status: 404 });
    }),
  );
});

describe("SessionProvider 401", () => {
  beforeEach(() => {
    meState.calls = 0;
    localStorage.clear();
  });

  it("calls /me once, clears the token, and lands on /", async () => {
    const { saveToken, getToken } = await import("../api/session");
    const { createAppQueryClient } = await import("./queryClient");
    const { RequireAuth } = await import("./guards");
    const { SessionProvider } = await import("./session");

    saveToken("stale-token");
    const queryClient = createAppQueryClient();

    const router = createMemoryRouter(
      [
        {
          element: (
            <SessionProvider>
              <Outlet />
            </SessionProvider>
          ),
          children: [
            { path: "/", element: <div>sign-in</div> },
            {
              element: <RequireAuth />,
              children: [{ path: "/workspace", element: <div>workspace</div> }],
            },
          ],
        },
      ],
      { initialEntries: ["/workspace"] },
    );

    render(
      <QueryClientProvider client={queryClient}>
        <RouterProvider router={router} />
      </QueryClientProvider>,
    );

    await waitFor(() => {
      expect(meState.calls).toBe(1);
    });

    await waitFor(() => {
      expect(router.state.location.pathname).toBe("/");
    });

    expect(getToken()).toBeNull();
    expect(screen.getByText("sign-in")).toBeInTheDocument();
  });
});
