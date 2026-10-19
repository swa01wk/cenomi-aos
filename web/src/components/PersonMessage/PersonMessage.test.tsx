import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { PersonMessage } from "./PersonMessage";

describe("PersonMessage", () => {
  it("shows author name", () => {
    render(
      <PersonMessage
        turn={{
          turn_id: "t1",
          seq: 1,
          author: { kind: "person", id: "p1", name: "Alex Kim" },
          blocks: [{ kind: "text", text: "Hello" }],
          at: "2026-01-01T12:00:00Z",
        }}
      />,
    );
    expect(screen.getByText(/Alex Kim/)).toBeInTheDocument();
    expect(screen.getByText("Hello")).toBeInTheDocument();
  });
});
