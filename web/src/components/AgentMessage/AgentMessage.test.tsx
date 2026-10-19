import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { AgentMessage } from "./AgentMessage";

describe("AgentMessage", () => {
  it("renders text blocks literally without HTML", () => {
    render(
      <AgentMessage
        turn={{
          turn_id: "t1",
          seq: 1,
          author: { kind: "seat", id: "s1", name: "Assistant" },
          blocks: [{ kind: "text", text: "<b>x</b>" }],
          at: "2026-01-01T00:00:00Z",
        }}
      />,
    );
    expect(screen.getByText("<b>x</b>")).toBeInTheDocument();
    expect(document.querySelector("b")).toBeNull();
  });
});

describe("AgentMessage blocks", () => {
  const turn = (blocks: Parameters<typeof AgentMessage>[0]["turn"]["blocks"]) => ({
    turn_id: "t2",
    seq: 2,
    author: { kind: "seat" as const, id: "s1", name: "Assistant" },
    blocks,
    at: "2026-01-01T00:00:00Z",
  });

  it("renders a notice without a tone as a notice, keyed on kind", () => {
    render(<AgentMessage turn={turn([{ kind: "notice", text: "Saved as a draft" }])} />);
    expect(screen.getByText("Saved as a draft").tagName).toBe("P");
  });

  it("renders a refusal block with the RefusalNotice component", () => {
    render(
      <AgentMessage
        turn={turn([{ kind: "refusal", title: "Not shared with your role", decision_id: "pd_1", rule: "rule_a" }])}
      />,
    );
    expect(screen.getByRole("note")).toHaveTextContent("Not shared with your role");
    expect(screen.getByRole("note")).toHaveTextContent("decision pd_1");
  });

  it("ignores a block kind it doesn't know", () => {
    render(<AgentMessage turn={turn([{ kind: "text", text: "Hello" }, { kind: "unknown" } as never])} />);
    expect(screen.getByText("Hello")).toBeInTheDocument();
  });
});
