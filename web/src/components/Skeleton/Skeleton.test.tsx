import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Skeleton } from "./Skeleton";

describe("Skeleton", () => {
  it("exposes busy state", () => {
    render(<Skeleton />);
    expect(screen.getByLabelText("Loading")).toHaveAttribute("aria-busy", "true");
  });
});
