import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ConnectionBanner } from "./ConnectionBanner";

describe("ConnectionBanner", () => {
  it("shows reconnecting", () => {
    render(<ConnectionBanner mode="reconnecting" />);
    expect(screen.getByText(/Reconnecting/)).toBeInTheDocument();
  });
});
