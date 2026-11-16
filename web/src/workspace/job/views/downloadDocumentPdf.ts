import { jsPDF } from "jspdf";
import type { components } from "../../../api/schema";
import { formatFieldValue } from "./formatFieldValue";

type ArtifactView = components["schemas"]["ArtifactView"];
type FieldDef = ArtifactView["fields"][number];

const PAGE_MARGIN = 14;
const LINE_HEIGHT = 6;
const BOTTOM = 285;

function fieldDisplayText(field: FieldDef, raw: unknown): string {
  if (raw == null || raw === "" || (Array.isArray(raw) && raw.length === 0)) {
    return "";
  }
  if (field.type === "list" && Array.isArray(raw)) {
    return raw.map((item) => (typeof item === "string" ? item : JSON.stringify(item))).join("\n");
  }
  return formatFieldValue(field, raw).text;
}

function sanitizeFileName(stem: string): string {
  const cleaned = stem
    .trim()
    .replace(/[^\w\s-]/g, "")
    .replace(/\s+/g, "-")
    .slice(0, 80);
  return cleaned || "Master-RFP";
}

/** Build a shareable PDF from a document artifact the caller is already allowed to see. */
export function downloadDocumentPdf(options: {
  view: ArtifactView;
  content: Record<string, unknown>;
  documentHeading: string;
  fileStem: string;
}): void {
  const { view, content, documentHeading, fileStem } = options;
  const order = view.columns?.length ? view.columns : view.fields.map((f) => f.name);
  const byName = new Map(view.fields.map((f) => [f.name, f]));
  const fields = order.map((n) => byName.get(n)).filter((f): f is FieldDef => Boolean(f));

  const doc = new jsPDF({ unit: "mm", format: "a4" });
  const width = doc.internal.pageSize.getWidth() - PAGE_MARGIN * 2;
  let y = PAGE_MARGIN;

  const ensureSpace = (needed: number) => {
    if (y + needed > BOTTOM) {
      doc.addPage();
      y = PAGE_MARGIN;
    }
  };

  doc.setFont("helvetica", "bold");
  doc.setFontSize(16);
  doc.text(documentHeading, PAGE_MARGIN, y);
  y += 10;

  doc.setFont("helvetica", "normal");
  doc.setFontSize(10);

  for (const field of fields) {
    const text = fieldDisplayText(field, content[field.name]);
    if (!text || text === "—") continue;

    ensureSpace(LINE_HEIGHT * 2);
    doc.setFont("helvetica", "bold");
    doc.setFontSize(9);
    doc.text(field.label.toUpperCase(), PAGE_MARGIN, y);
    y += LINE_HEIGHT;

    doc.setFont("helvetica", "normal");
    doc.setFontSize(10);
    const lines = doc.splitTextToSize(text, width);
    for (const line of lines) {
      ensureSpace(LINE_HEIGHT);
      doc.text(line, PAGE_MARGIN, y);
      y += LINE_HEIGHT;
    }
    y += 3;
  }

  doc.save(`${sanitizeFileName(fileStem)}.pdf`);
}

export function masterRfpPdfFileStem(content: Record<string, unknown>): string {
  const title = content.title;
  if (typeof title === "string" && title.trim()) {
    return `Master-RFP-${title.trim()}`;
  }
  return "Master-RFP";
}
