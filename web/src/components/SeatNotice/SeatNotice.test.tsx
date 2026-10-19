import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { SeatNotice } from "./SeatNotice";

describe("SeatNotice", () => {
  it("shows title", () => {
    render(<SeatNotice code="seat_not_active" title="Seat paused" />);
    expect(screen.getByText("Seat paused")).toBeInTheDocument();
  });
});
