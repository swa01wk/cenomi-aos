import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MeterBar } from "./MeterBar";

describe("MeterBar", () => {
  it("shows label and values", () => {
    render(<MeterBar label="Spend today" value={2} limit={10} />);
    expect(screen.getByText("Spend today")).toBeInTheDocument();
    expect(screen.getByText("2 / 10")).toBeInTheDocument();
  });
});
