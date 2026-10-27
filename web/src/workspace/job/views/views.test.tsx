import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import type { components } from "../../../api/schema";
import { artifactViewComponent } from "./index";

type ArtifactView = components["schemas"]["ArtifactView"];
type ArtifactVersion = components["schemas"]["ArtifactVersion"];

const fields: ArtifactView["fields"] = [
  { name: "item_code", label: "Item code", type: "string" },
  { name: "units", label: "Units", type: "integer" },
  { name: "eta", label: "ETA", type: "date" },
  { name: "fee", label: "Fee", type: "money" },
];

const documentView: ArtifactView = {
  type: "document",
  fields: [{ name: "title", label: "Title", type: "string" }, ...fields],
};

const sheetView: ArtifactView = {
  type: "sheet",
  columns: ["item_code", "units"],
  fields,
};

function version(content: Record<string, unknown>): ArtifactVersion {
  return {
    artifact_id: "art-1",
    artifact_type: "widget_record",
    version: 1,
    content: content as ArtifactVersion["content"],
    hidden_fields: [],
    produced_by: { kind: "attempt", id: "a1", name: "Worker" },
    created_at: "2026-01-01T00:00:00Z",
  };
}

describe("artifact views", () => {
  afterEach(() => cleanup());

  it("renders document view from fixture labels", () => {
    const View = artifactViewComponent("document");
    render(
      <View
        view={documentView}
        version={version({
          title: "North site restock",
          item_code: "WX-9",
          units: 12,
          eta: "2026-06-01",
          fee: { amount: 400, currency: "USD" },
        })}
      />,
    );
    expect(screen.getByText("Title")).toBeInTheDocument();
    expect(screen.getByText("North site restock")).toBeInTheDocument();
    expect(screen.getByText(new Intl.NumberFormat(undefined, { style: "currency", currency: "USD" }).format(400))).toBeInTheDocument();
    expect(screen.getByText("Item code")).toBeInTheDocument();
    expect(screen.getByText("WX-9")).toBeInTheDocument();
    expect(screen.getByText("12")).toBeInTheDocument();
  });

  it("renders sheet rows from the columns", () => {
    const View = artifactViewComponent("sheet");
    render(
      <View
        view={{ ...sheetView, row_key: "item_code" }}
        version={version({
          rows: [
            { item_code: "WX-9", units: 12 },
            { item_code: "ZX-1", units: 3 },
          ],
        })}
      />,
    );
    expect(screen.getByText("Item code")).toBeInTheDocument();
    expect(screen.getByText("WX-9")).toBeInTheDocument();
    expect(screen.getByText("ZX-1")).toBeInTheDocument();
    expect(screen.getByText("12")).toBeInTheDocument();
  });

  it("renders fallback field list for unknown view types", () => {
    const View = artifactViewComponent("dashboard");
    render(
      <View
        view={sheetView}
        version={version({ item_code: "ZX-1", units: 3, eta: "2026-07-01", fee: 10 })}
      />,
    );
    expect(screen.getByText("Units")).toBeInTheDocument();
    expect(screen.getByText("3")).toBeInTheDocument();
  });

  it("formats a bare number in a money field without inventing a currency", () => {
    const View = artifactViewComponent("document");
    render(<View view={documentView} version={version({ fee: 10 })} />);
    expect(screen.getByText(new Intl.NumberFormat(undefined, { minimumFractionDigits: 2 }).format(10))).toBeInTheDocument();
  });

  it("shows hidden-fields note", () => {
    const View = artifactViewComponent("document");
    render(
      <View
        view={documentView}
        version={{
          ...version({ title: "T" }),
          hidden_fields: ["fee"],
        }}
      />,
    );
    expect(screen.getByText("Some fields aren't shared with your role")).toBeInTheDocument();
  });
});
