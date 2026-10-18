import { QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { createMemoryRouter, Outlet, RouterProvider } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { RequireAuth, RequireConsole } from "./guards";
import SignInPage from "./SignInPage";
import { createAppQueryClient } from "./queryClient";
import type { Me } from "./session";
import { SessionProvider, useSession } from "./session";

type Person = Me & { id: string };

const auth = vi.hoisted(() => ({
  active: null as string | null,
}));

const PEOPLE: Record<string, Person> = {
  faisal: {
    id: "faisal",
    name: "Faisal",
    team: "facilities/operations",
    roles: ["end_user"],
    console: false,
    org: "cenomi",
  },
  noura: {
    id: "noura",
    name: "Noura",
    team: "procurement/sourcing",
    roles: ["sourcing_user"],
    console: false,
    org: "cenomi",
  },
  risk: {
    id: "risk",
    name: "Risk reviewer",
    team: "platform/platform",
    roles: ["risk"],
    console: true,
    org: "cenomi",
  },
  platform_admin: {
    id: "platform_admin",
    name: "Platform admin",
    team: "platform/platform",
    roles: ["platform_admin"],
    console: true,
    org: "cenomi",
  },
};

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
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = toUrl(input);
      const method =
        (input instanceof Request ? input.method : init?.method)?.toUpperCase() ?? "GET";
      const bodyText =
        input instanceof Request && input.method !== "GET" && input.method !== "HEAD"
          ? await input.clone().text()
          : init?.body
            ? String(init.body)
            : "";
      if (url.includes("/auth/personas")) {
        return Response.json(Object.values(PEOPLE));
      }
      if (url.includes("/auth/session") && method === "POST") {
        const body = JSON.parse(bodyText) as { person_id: string };
        auth.active = body.person_id;
        return Response.json({ token: `token-${body.person_id}` });
      }
      if (url.includes("/me")) {
        if (!auth.active) {
          return Response.json(
            { type: "about:blank", title: "Sign in required", status: 401, code: "unauthenticated" },
            { status: 401, headers: { "content-type": "application/problem+json" } },
          );
        }
        return Response.json(PEOPLE[auth.active]);
      }
      return Response.json({}, { status: 404 });
    }),
  );
});

function WorkspacePage() {
  const { signOut } = useSession();
  return (
    <div>
      <div data-testid="page">workspace</div>
      <button type="button" onClick={signOut}>
        Sign out
      </button>
    </div>
  );
}

function ConsoleAuditPage() {
  const { signOut } = useSession();
  return (
    <div>
      <div data-testid="page">console-audit</div>
      <button type="button" onClick={signOut}>
        Sign out
      </button>
    </div>
  );
}

function ConsolePacksPage() {
  const { signOut } = useSession();
  return (
    <div>
      <div data-testid="page">console-packs</div>
      <button type="button" onClick={signOut}>
        Sign out
      </button>
    </div>
  );
}

function makeRouter(initialEntries: string[]) {
  const queryClient = createAppQueryClient();

  const router = createMemoryRouter(
    [
      {
        element: (
          <QueryClientProvider client={queryClient}>
            <SessionProvider>
              <Outlet />
            </SessionProvider>
          </QueryClientProvider>
        ),
        children: [
          { path: "/", element: <SignInPage /> },
          {
            element: <RequireAuth />,
            children: [
              { path: "/workspace", element: <WorkspacePage /> },
              {
                element: <RequireConsole />,
                children: [
                  { path: "/console/audit", element: <ConsoleAuditPage /> },
                  { path: "/console/packs", element: <ConsolePacksPage /> },
                ],
              },
            ],
          },
        ],
      },
    ],
    { initialEntries },
  );

  return router;
}

async function pickPerson(name: string) {
  await waitFor(() => {
    expect(screen.getByRole("button", { name: new RegExp(name, "i") })).toBeInTheDocument();
  });
  fireEvent.click(screen.getByRole("button", { name: new RegExp(name, "i") }));
}

async function expectPath(router: ReturnType<typeof createMemoryRouter>, pathname: string) {
  await waitFor(() => {
    expect(router.state.location.pathname).toBe(pathname);
  });
}

describe("sign-out does not carry deep links to the next person", () => {
  beforeEach(() => {
    cleanup();
    auth.active = null;
    localStorage.clear();
  });

  it("workspace → sign out → risk lands on console audit", async () => {
    const router = makeRouter(["/"]);
    render(<RouterProvider router={router} />);

    await pickPerson("Faisal");
    await expectPath(router, "/workspace");

    fireEvent.click(within(screen.getByTestId("page").parentElement!).getByRole("button", { name: "Sign out" }));
    await expectPath(router, "/");

    await pickPerson("Risk reviewer");
    await expectPath(router, "/console/audit");
  });

  it("platform admin → sign out → workspace person lands on workspace", async () => {
    const router = makeRouter(["/"]);
    render(<RouterProvider router={router} />);

    await pickPerson("Platform admin");
    await expectPath(router, "/console/packs");

    fireEvent.click(within(screen.getByTestId("page").parentElement!).getByRole("button", { name: "Sign out" }));
    await expectPath(router, "/");

    await pickPerson("Noura");
    await expectPath(router, "/workspace");
  });

  it("signed-out deep link to console audit works for a console person", async () => {
    const router = makeRouter(["/console/audit"]);
    render(<RouterProvider router={router} />);

    await waitFor(() => {
      expect(screen.getByRole("heading", { level: 1, name: "Sign in" })).toBeInTheDocument();
    });

    await pickPerson("Risk reviewer");
    await expectPath(router, "/console/audit");
  });

  it("signed-out console deep link is ignored for workspace-only accounts", async () => {
    const router = makeRouter(["/console/packs"]);
    render(<RouterProvider router={router} />);

    await waitFor(() => {
      expect(screen.getByRole("heading", { level: 1, name: "Sign in" })).toBeInTheDocument();
    });

    await pickPerson("Faisal");
    await expectPath(router, "/workspace");
  });
});
