import type { components } from "../../api/schema";

type ArtifactView = components["schemas"]["ArtifactView"];

/** Plain-language request summary from brief draft fields (pack-neutral via view labels). */
export function briefSummaryProse(
  content: Record<string, unknown>,
  view: ArtifactView,
): string {
  const order = view.columns?.length ? view.columns : view.fields.map((f) => f.name);
  const byName = new Map(view.fields.map((f) => [f.name, f]));

  const parts: string[] = [];
  const title = content.title;
  const qty = content.quantity;
  if (title != null && String(title).trim()) {
    const q = typeof qty === "number" && qty > 0 ? `${qty}× ` : "";
    parts.push(`You need ${q}${String(title).trim()}.`);
  } else if (typeof qty === "number" && qty > 0) {
    parts.push(`You need quantity ${qty}.`);
  }

  for (const name of order) {
    const field = byName.get(name);
    if (!field || name === "title" || name === "quantity") continue;
    const raw = content[name];
    if (raw == null || raw === "" || (Array.isArray(raw) && raw.length === 0)) continue;
    if (field.type === "list" && Array.isArray(raw)) {
      parts.push(`${field.label}: ${raw.map(String).join(", ")}.`);
      continue;
    }
    if (field.type === "money" && typeof raw === "object" && raw !== null && "amount" in raw) {
      const amount = (raw as { amount?: unknown }).amount;
      if (amount != null && amount !== "") {
        parts.push(`${field.label}: ${amount}.`);
      }
      continue;
    }
    parts.push(`${field.label}: ${String(raw).trim()}.`);
  }

  if (!parts.length) return "I'm drafting your request from what you've told me so far.";
  return parts.join(" ");
}
