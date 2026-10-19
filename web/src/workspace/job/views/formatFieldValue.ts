import type { components } from "../../../api/schema";

type FieldDef = components["schemas"]["ArtifactView"]["fields"][number];

export function formatFieldValue(
  field: FieldDef,
  value: unknown,
): { text: string; alignRight?: boolean } {
  if (value == null || value === "") return { text: "—" };

  switch (field.type) {
    case "money": {
      // The contract carries no currency on the field, so only a {amount, currency} value shows one.
      if (typeof value === "object" && value !== null && "amount" in value) {
        const { amount, currency } = value as { amount?: unknown; currency?: unknown };
        const n = Number(amount);
        if (!Number.isFinite(n)) return { text: String(amount) };
        if (typeof currency === "string" && currency) {
          try {
            return {
              text: new Intl.NumberFormat(undefined, { style: "currency", currency }).format(n),
              alignRight: true,
            };
          } catch {
            return { text: `${currency} ${n.toFixed(2)}`, alignRight: true };
          }
        }
        return { text: new Intl.NumberFormat(undefined, { minimumFractionDigits: 2 }).format(n), alignRight: true };
      }
      const n = typeof value === "number" ? value : Number(value);
      if (!Number.isFinite(n)) return { text: String(value) };
      return { text: new Intl.NumberFormat(undefined, { minimumFractionDigits: 2 }).format(n), alignRight: true };
    }
    case "date": {
      const d = new Date(String(value));
      if (Number.isNaN(d.getTime())) return { text: String(value) };
      return { text: d.toLocaleDateString() };
    }
    case "datetime": {
      const d = new Date(String(value));
      if (Number.isNaN(d.getTime())) return { text: String(value) };
      return { text: d.toLocaleString() };
    }
    case "integer":
      return { text: String(value), alignRight: true };
    case "number":
      return { text: String(value), alignRight: true };
    case "boolean":
      return { text: value ? "Yes" : "No" };
    case "list":
      return { text: Array.isArray(value) ? value.join(", ") : String(value) };
    case "object":
      return { text: JSON.stringify(value) };
    default:
      return { text: String(value) };
  }
}
