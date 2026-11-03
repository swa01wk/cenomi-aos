import { describe, expect, it } from "vitest";
import { briefSummaryProse } from "./briefSummaryProse";
import type { components } from "../../api/schema";

const view: components["schemas"]["ArtifactView"] = {
  type: "document",
  fields: [
    { name: "title", label: "Title", type: "string" },
    { name: "quantity", label: "Quantity", type: "integer" },
    { name: "specification", label: "Specification", type: "text" },
    { name: "delivery_date", label: "Delivery date", type: "date" },
    { name: "delivery_site", label: "Delivery site", type: "string" },
  ],
  columns: ["title", "quantity", "specification", "delivery_date", "delivery_site"],
};

describe("briefSummaryProse", () => {
  it("builds a readable summary from brief content", () => {
    const text = briefSummaryProse(
      {
        title: "MacBook",
        quantity: 10,
        specification: "M4, 8GB, 256GB, Space Grey, Arabic keyboard",
        delivery_date: "2026-12-10",
        delivery_site: "Al Nakheel Mall, Dammam",
      },
      view,
    );
    expect(text).toContain("10× MacBook");
    expect(text).toContain("Specification:");
    expect(text).toContain("Al Nakheel Mall");
  });
});
