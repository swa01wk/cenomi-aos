import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";
import PacksPage from "./PacksPage";

const { getMock, postMock } = vi.hoisted(() => ({
  getMock: vi.fn(),
  postMock: vi.fn(),
}));

vi.mock("../api/client", () => ({
  client: {
    GET: getMock,
    POST: postMock,
  },
}));

vi.mock("./useOrgPeople", () => ({
  useOrgPeople: () => ({
    personName: (id: string) => (id === "risk_reviewer" ? "Risk reviewer" : id),
  }),
}));

vi.mock("react-router", async (importOriginal) => {
  const actual = await importOriginal<typeof import("react-router")>();
  return {
    ...actual,
    useOutletContext: () => ({ canSync: true }),
  };
});

function wrap(ui: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return (
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <div>{ui}</div>
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe("PacksPage publish panel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    getMock.mockImplementation(async (path: string) => {
      if (path === "/console/packs") {
        return {
          data: {
            available: ["demo_pack"],
            packs: [
              {
                name: "demo_pack",
                owner: "pack_owner",
                versions: [
                  {
                    id: "ver-1",
                    version: 1,
                    status: "validated",
                    digest: "abc",
                    errors: 0,
                    warnings: 0,
                    source: "console",
                    created_by: "platform_admin",
                    created_at: "2026-01-01T00:00:00Z",
                  },
                ],
              },
            ],
          },
        };
      }
      if (path === "/console/publish-requests") {
        return {
          data: {
            items: [
              {
                id: "PR-1",
                pack_version_id: "ver-1",
                status: "open",
                requested_by: "platform_admin",
                requested_at: "2026-01-02T00:00:00Z",
                parts: [
                  { part: "policies", role: "risk", status: "open" },
                  { part: "seats_and_workflows", role: "owner", status: "open" },
                ],
              },
            ],
          },
        };
      }
      if (path === "/org") {
        return { data: { people: [], departments: [], organization: { id: "o", name: "Org" } } };
      }
      throw new Error(`unexpected GET ${path}`);
    });
    postMock.mockResolvedValue({ data: {} });
  });

  it("renders publish parts and sends approve with the right part", async () => {
    render(wrap(<PacksPage />));

    await waitFor(() => {
      expect(screen.getByText(/Publish request PR-1/)).toBeInTheDocument();
    });
    expect(screen.getByText(/Policies/)).toBeInTheDocument();
    expect(screen.getByText(/Seats and workflows/)).toBeInTheDocument();

    const approveButtons = screen.getAllByRole("button", { name: "Approve" });
    fireEvent.click(approveButtons[0]!);

    await waitFor(() => {
      expect(postMock).toHaveBeenCalledWith("/console/publish-requests/{id}/approve", {
        params: { path: { id: "PR-1" } },
        body: { part: "policies" },
      });
    });
  });
});
