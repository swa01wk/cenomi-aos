import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { RequireAuth, RequireConsole } from "./guards";

const useSession = vi.fn();

vi.mock("./session", () => ({
  useSession: () => useSession(),
}));

describe("RequireAuth", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("redirects signed-out users to sign-in", () => {
    useSession.mockReturnValue({ me: null, booting: false });
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
    localStorage.setItem("aos.token", "tok");
    useSession.mockReturnValue({ me: null, booting: true });
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
});

describe("RequireConsole", () => {
  it("refuses workspace-only accounts on console routes", () => {
    useSession.mockReturnValue({
      me: { id: "p1", name: "Faisal", team: "ops/ops", roles: ["requester"], console: false, org: "org" },
      booting: false,
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
});
