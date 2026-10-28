import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { client } from "../../api/client";
import type { components } from "../../api/schema";
import { DecisionCard } from "./DecisionCard";

vi.mock("../../api/client", () => ({
  client: { GET: vi.fn() },
}));

type PendingItem = components["schemas"]["PendingItem"];

const pending: PendingItem = {
  pending_id: "pend_1",
  instance_id: "JOB-1",
  kind: "decision",
  title: "Confirm the brief",
  for_role: "requester",
  status: "open",
  created_at: "2026-10-27T10:00:00Z",
  options: [{ value: "confirm", label: "Confirm the brief" }],
  artifact_ref: { artifact_id: "art_1", version: 2 },
};

afterEach(() => cleanup());

describe("DecisionCard", () => {
  it("prefills an editable approval comment for the brief", () => {
    render(<DecisionCard pending={pending} onApprove={vi.fn()} />);
    expect(screen.getByDisplayValue("Approved, please go ahead.")).toBeInTheDocument();
  });

  it("approves with the comment and the brief version", async () => {
    const onApprove = vi.fn().mockResolvedValue(undefined);
    render(<DecisionCard pending={pending} onApprove={onApprove} />);
    fireEvent.change(screen.getByDisplayValue("Approved, please go ahead."), { target: { value: "Looks right" } });
    fireEvent.click(screen.getByRole("button", { name: "Confirm the brief" }));
    expect(onApprove).toHaveBeenCalledWith(
      expect.objectContaining({
        pendingId: "pend_1",
        value: "confirm",
        artifactVersion: 2,
        note: "Looks right",
      }),
    );
  });

  it("sends the default note when the user confirms without editing", async () => {
    const onApprove = vi.fn().mockResolvedValue(undefined);
    render(<DecisionCard pending={pending} onApprove={onApprove} />);
    fireEvent.click(screen.getByRole("button", { name: "Confirm the brief" }));
    expect(onApprove).toHaveBeenCalledWith(
      expect.objectContaining({ note: "Approved, please go ahead." }),
    );
  });

  it("sends the chosen rows once enough are selected", async () => {
    vi.mocked(client.GET).mockResolvedValue({
      data: {
        artifact_id: "art_1",
        artifact_type: "supplier_list",
        version: 8,
        content: {
          rows: [
            { supplier_id: "s1", supplier: "One" },
            { supplier_id: "s2", supplier: "Two" },
            { supplier_id: "s3", supplier: "Three" },
          ],
        },
        hidden_fields: [],
        produced_by: { kind: "attempt", id: "a", name: "Worker" },
        created_at: "2026-10-27T10:00:00Z",
      },
      error: undefined,
      response: new Response(),
    });
    const onApprove = vi.fn().mockResolvedValue(undefined);
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <DecisionCard
          pending={{
            ...pending,
            title: "Confirm the shortlist",
            event: "decision.shortlist_confirmed",
            detail: "Choose at least 3.",
            select_min: 3,
            options: [{ value: "confirm", label: "Confirm the shortlist" }],
            artifact_ref: { artifact_id: "art_1", version: 8 },
          }}
          view={{
            type: "sheet",
            row_key: "supplier_id",
            columns: ["supplier"],
            fields: [{ name: "supplier", label: "Supplier", type: "string" }, { name: "supplier_id", label: "Id", type: "string" }],
          }}
          onApprove={onApprove}
        />
      </QueryClientProvider>,
    );
    expect(await screen.findByRole("checkbox", { name: "One" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /^Confirm the shortlist/ }));
    expect(onApprove).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("checkbox", { name: "One" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Two" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Three" }));
    fireEvent.click(screen.getByRole("button", { name: /^Confirm the shortlist/ }));
    expect(onApprove).toHaveBeenCalledWith(
      expect.objectContaining({ selection: ["s1", "s2", "s3"], artifactVersion: 8 }),
    );
  });
});
