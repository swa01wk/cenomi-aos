import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MeterBar } from "./MeterBar";

describe("MeterBar", () => {
  it("shows label and values", () => {
    render(<MeterBar label="Spend today" value={2} limit={10} />);
    expect(screen.getByText("Spend today")).toBeInTheDocument();
    expect(screen.getByText("2 / 10")).toBeInTheDocument();
  });

  it("can leave the numbers to the label", () => {
    // No automatic cleanup between tests here, so query inside this render only.
    const { container } = render(<MeterBar label="USD 2.00 of 10.00" value={2} limit={10} showValues={false} />);
    expect(within(container).queryByText("2 / 10")).toBeNull();
    expect(within(container).getByLabelText("USD 2.00 of 10.00")).toBeInTheDocument();
  });
});
