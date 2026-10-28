import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import QueuePage from "./QueuePage";

const { GET, POST, useSession } = vi.hoisted(() => ({
  GET: vi.fn(),
  POST: vi.fn(),
  useSession: vi.fn(),
}));

vi.mock("../app/session", () => ({ useSession: () => useSession() }));
vi.mock("../api/client", () => ({
  client: {
    GET: (...args: unknown[]) => GET(...args),
    POST: (...args: unknown[]) => POST(...args),
  },
}));

const job = {
  instance_id: "JOB-9",
  title: "Restock the loading bay",
  workflow: "replenish",
  state: "intake",
  state_label: "Intake",
  version: 3,
  claim_role: "buyer",
};

function renderQueue() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <QueuePage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("QueuePage", () => {
  afterEach(() => cleanup());

  beforeEach(() => {
    GET.mockReset();
    POST.mockReset();
    useSession.mockReturnValue({ me: { id: "p1", name: "N", team: "ops/floor", roles: [], console: false, org: "o" } });
    GET.mockImplementation(async (path: string) => {
      if (path === "/workspace/digital-workers") return { data: { items: [] } };
      return { data: { items: [job] } };
    });
  });

  it("asks for a comment before approving or rejecting", async () => {
    renderQueue();
    const reject = await screen.findByRole("button", { name: /Reject/ });
    const approve = screen.getByRole("button", { name: /Approve/ });
    expect(reject).toHaveAttribute("aria-disabled", "true");
    expect(approve).toHaveAttribute("aria-disabled", "true");
    fireEvent.change(screen.getByPlaceholderText("Comment"), { target: { value: "Not enough detail" } });
    expect(reject).not.toHaveAttribute("aria-disabled", "true");
    fireEvent.click(reject);
    await waitFor(() => expect(POST).toHaveBeenCalled());
    expect(POST).toHaveBeenCalledWith("/instances/{id}/claim", {
      params: { path: { id: "JOB-9" } },
      body: { role: "buyer", expected_version: 3, decision: "reject", note: "Not enough detail" },
    });
  });
});
