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
