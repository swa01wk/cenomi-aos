import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { DataTable } from "./DataTable";

describe("DataTable", () => {
  it("shows empty node when no rows", () => {
    render(
      <DataTable
        columns={[{ id: "n", header: "Name", render: (r: { n: string }) => r.n }]}
        rows={[]}
        getRowKey={() => "x"}
        empty={<span>Nothing here</span>}
      />,
    );
    expect(screen.getByText("Nothing here")).toBeInTheDocument();
  });
});
