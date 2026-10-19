import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { joinDeltas } from "./joinDeltas";
import { StreamingText } from "./StreamingText";

describe("joinDeltas", () => {
  it("ignores duplicate and replayed lower seq", () => {
    const text = joinDeltas([
      { instance_id: "i", turn_id: "t", seq: 1, text: "A" },
      { instance_id: "i", turn_id: "t", seq: 2, text: "B" },
      { instance_id: "i", turn_id: "t", seq: 1, text: "X" },
      { instance_id: "i", turn_id: "t", seq: 3, text: "C" },
    ]);
    expect(text).toBe("ABC");
  });

  it("renders literal HTML as text", () => {
    render(
      <StreamingText
        turnId="t1"
        deltas={[{ instance_id: "i", turn_id: "t1", seq: 1, text: "<b>x</b>" }]}
      />,
    );
    expect(screen.getByText("<b>x</b>")).toBeInTheDocument();
    expect(document.querySelector("b")).toBeNull();
  });
});
