import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { createMemoryRouter, MemoryRouter, Route, RouterProvider, Routes, useLocation } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { RequireAuth, RequireConsole } from "./guards";

const useSession = vi.fn();

vi.mock("./session", () => ({
  useSession: () => useSession(),
}));

describe("RequireAuth", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("redirects signed-out users to sign-in", () => {
    useSession.mockReturnValue({
      me: null,
      hasToken: false,
      booting: false,
      sessionError: null,
      retrySession: vi.fn(),
      sessionJustEnded: () => false,
    });
    render(
      <MemoryRouter initialEntries={["/workspace"]}>
        <Routes>
          <Route path="/" element={<div>sign-in</div>} />
          <Route element={<RequireAuth />}>
            <Route path="/workspace" element={<div>workspace</div>} />
          </Route>
        </Routes>
      </MemoryRouter>,
    );
    expect(screen.getByText("sign-in")).toBeInTheDocument();
  });

  it("shows loading while session bootstraps", () => {
    useSession.mockReturnValue({
      me: null,
      hasToken: true,
      booting: true,
      sessionError: null,
      retrySession: vi.fn(),
      sessionJustEnded: () => false,
    });
    render(
      <MemoryRouter initialEntries={["/workspace"]}>
        <Routes>
          <Route element={<RequireAuth />}>
            <Route path="/workspace" element={<div>workspace</div>} />
          </Route>
        </Routes>
      </MemoryRouter>,
    );
    expect(screen.getByText(/Loading your session/)).toBeInTheDocument();
  });

  it("shows retry when session load fails", () => {
    const retrySession = vi.fn();
    useSession.mockReturnValue({
      me: null,
      hasToken: true,
      booting: false,
      sessionError: new Error("Service unavailable"),
      retrySession,
      sessionJustEnded: () => false,
    });
    render(
      <MemoryRouter initialEntries={["/workspace"]}>
        <Routes>
          <Route element={<RequireAuth />}>
            <Route path="/workspace" element={<div>workspace</div>} />
          </Route>
        </Routes>
      </MemoryRouter>,
    );
    expect(screen.getByText(/Can't load your session/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(retrySession).toHaveBeenCalled();
  });
});

describe("RequireConsole", () => {
  it("refuses workspace-only accounts on console routes", () => {
    useSession.mockReturnValue({
      me: { id: "p1", name: "Faisal", team: "ops/ops", roles: ["requester"], console: false, org: "org" },
      hasToken: true,
      booting: false,
      sessionError: null,
      retrySession: vi.fn(),
      sessionJustEnded: () => false,
    });
    render(
      <MemoryRouter initialEntries={["/console/packs"]}>
        <Routes>
          <Route element={<RequireConsole />}>
            <Route path="/console/packs" element={<div>packs</div>} />
          </Route>
        </Routes>
      </MemoryRouter>,
    );
    expect(screen.getByText(/Console not available/)).toBeInTheDocument();
  });

  it("preserves query string in from state when redirecting to sign-in", async () => {
    useSession.mockReturnValue({
      me: null,
      hasToken: false,
      booting: false,
      sessionError: null,
      retrySession: vi.fn(),
      sessionJustEnded: () => false,
    });

    function Capture() {
      const loc = useLocation();
      return <div data-testid="from">{(loc.state as { from?: string })?.from ?? ""}</div>;
    }

    const router = createMemoryRouter(
      [
        { path: "/", element: <Capture /> },
        {
          element: <RequireConsole />,
          children: [{ path: "/console/packs", element: <div>packs</div> }],
        },
      ],
      { initialEntries: ["/console/packs?tab=1"] },
    );

    render(<RouterProvider router={router} />);

    await waitFor(() => {
      expect(router.state.location.pathname).toBe("/");
    });
    expect(screen.getByTestId("from").textContent).toBe("/console/packs?tab=1");
  });
});
