import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { components } from "../api/schema";
import SeatPage from "./SeatPage";

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
    personName: (id: string) => (id === "platform_admin" ? "Platform admin" : id),
  }),
}));

const baseSeat = {
  name: "seat_alpha",
  display_name: "Alpha worker",
  version: 1,
  pack_version: "demo@1",
  placement: "team/a",
  state: "APPROVED" as const,
  availability: "UNAVAILABLE" as const,
  running_attempts: 0,
  spend_today_usd: 0,
  daily_limit_usd: 20,
  owner: "owner_person",
  record_version: 4,
  configured_by: "platform_admin",
  checks: [{ name: "limits", passed: true }],
  evals: [] as components["schemas"]["EvalRun"][],
  history: [
    { from: "DRAFT", to: "CONFIGURED", by: "platform_admin", at: "2026-01-01T10:00:00Z" },
    { from: "CONFIGURED", to: "TESTING", by: "platform_admin", at: "2026-01-02T10:00:00Z" },
    { from: "TESTING", to: "APPROVED", by: "risk_reviewer", at: "2026-01-03T10:00:00Z" },
  ],
};

async function clickActivate() {
  const actions = await screen.findByRole("region", { name: "Actions" });
  fireEvent.click(within(actions).getByRole("button", { name: "Activate" }));
}

function renderSeat(initialEvals: components["schemas"]["EvalRun"][] = baseSeat.evals) {
  let pollCount = 0;
  getMock.mockImplementation(async () => ({
    data: {
      ...baseSeat,
      evals: initialEvals.map((e) => ({ ...e })),
    },
  }));

  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const ui = (
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/console/seats/seat_alpha"]}>
        <Routes>
          <Route path="/console/seats/:seat" element={<SeatPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  );
  render(ui);
  return { qc, bumpPoll: () => pollCount++ };
}

describe("SeatPage", () => {
  afterEach(() => cleanup());

  beforeEach(() => {
    vi.clearAllMocks();
    getMock.mockImplementation(async () => ({ data: { ...baseSeat } }));
    postMock.mockResolvedValue({ data: baseSeat });
  });

  it("builds lifecycle steps from history", async () => {
    renderSeat();
    await waitFor(() => {
      expect(screen.getByText("Alpha worker")).toBeInTheDocument();
    });
    expect(screen.getByLabelText("Seat lifecycle")).toHaveTextContent("CONFIGURED");
    expect(screen.getByText(/Jan 1, 2026.*Platform admin/)).toBeInTheDocument();
  });

  it("sends expected_version on activate", async () => {
    renderSeat();
    await waitFor(() => expect(screen.getByText("Alpha worker")).toBeInTheDocument());
    await clickActivate();
    await waitFor(() => {
      expect(postMock).toHaveBeenCalledWith("/console/seats/{seat}/activate", {
        params: { path: { seat: "seat_alpha" } },
        body: { version: 1, expected_version: 4 },
      });
    });
  });

  it("shows RefusalNotice for segregation_of_duties on activate", async () => {
    postMock.mockReset();
    getMock.mockImplementation(async () => ({ data: { ...baseSeat } }));
    const { ApiProblemError } = await import("../api/problems");
    postMock.mockRejectedValueOnce(
      new ApiProblemError({
        type: "about:blank",
        title: "You cannot activate a seat you configured",
        status: 403,
        code: "segregation_of_duties",
        detail: "The Seat owner must activate.",
        rule: "seat.activate.not_configurer",
        decision_id: "DR-99",
      }),
    );

    renderSeat();
    await waitFor(() => expect(screen.getByText("Alpha worker")).toBeInTheDocument());
    await clickActivate();
    await waitFor(() => {
      expect(screen.getByText("You cannot activate a seat you configured")).toBeInTheDocument();
    });
    expect(screen.getByText(/seat\.activate\.not_configurer/)).toBeInTheDocument();
    expect(screen.getByText(/DR-99/)).toBeInTheDocument();
  });

  it("polls while an eval is running and stops after", async () => {
    let evals: components["schemas"]["EvalRun"][] = [
      { id: "e1", suite: "suite_a", model: "fake", status: "running" },
    ];
    getMock.mockImplementation(async () => ({
      data: { ...baseSeat, state: "TESTING", evals },
    }));

    renderSeat(evals);
    await waitFor(() => expect(screen.getByText("suite_a")).toBeInTheDocument());

    const callsBefore = getMock.mock.calls.length;
    await waitFor(() => expect(getMock.mock.calls.length).toBeGreaterThan(callsBefore), { timeout: 5000 });

    evals = [{ id: "e1", suite: "suite_a", model: "fake", status: "passed", passed: 1, total: 1 }];
    getMock.mockImplementation(async () => ({
      data: { ...baseSeat, state: "TESTING", evals },
    }));

    await waitFor(() => expect(screen.getByText("passed")).toBeInTheDocument(), { timeout: 5000 });
    const callsAfterPass = getMock.mock.calls.length;
    await new Promise((r) => setTimeout(r, 2000));
    expect(getMock.mock.calls.length).toBeLessThanOrEqual(callsAfterPass + 1);
  }, 15_000);
});
