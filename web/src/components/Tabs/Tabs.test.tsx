import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it } from "vitest";
import { Tabs } from "./Tabs";

function Harness() {
  const [active, setActive] = useState("a");
  return (
    <Tabs
      activeId={active}
      onChange={setActive}
      tabs={[
        { id: "a", label: "First", panel: <p>Panel A</p> },
        { id: "b", label: "Second", panel: <p>Panel B</p> },
      ]}
    />
  );
}

describe("Tabs", () => {
  it("switches panel and supports arrow keys", () => {
    render(<Harness />);
    expect(screen.getByText("Panel A")).toBeVisible();
    const first = screen.getByRole("tab", { name: "First" });
    fireEvent.keyDown(first, { key: "ArrowRight" });
    expect(screen.getByText("Panel B")).toBeVisible();
  });
});
