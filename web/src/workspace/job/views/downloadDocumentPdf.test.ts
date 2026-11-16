import { describe, expect, it } from "vitest";
import { masterRfpPdfFileStem } from "./downloadDocumentPdf";

describe("masterRfpPdfFileStem", () => {
  it("uses the document title when present", () => {
    expect(masterRfpPdfFileStem({ title: "Cenomi website RFP" })).toBe("Master-RFP-Cenomi website RFP");
  });

  it("falls back when title is missing", () => {
    expect(masterRfpPdfFileStem({})).toBe("Master-RFP");
  });
});
