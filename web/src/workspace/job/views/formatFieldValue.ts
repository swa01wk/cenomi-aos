import type { components } from "../../../api/schema";

type FieldDef = components["schemas"]["ArtifactView"]["fields"][number];

export function formatFieldValue(
  field: FieldDef,
  value: unknown,
): { text: string; alignRight?: boolean } {
  if (value == null || value === "") return { text: "—" };

  switch (field.type) {
    case "money": {
      const n = typeof value === "number" ? value : Number(value);
      if (!Number.isFinite(n)) return { text: String(value) };
      const currency =
        typeof value === "object" && value !== null && "currency" in value
          ? String((value as { currency?: string }).currency ?? "")
          : "";
      const amount =
        typeof value === "object" && value !== null && "amount" in value
          ? Number((value as { amount?: number }).amount)
          : n;
      try {
        return {
          text: new Intl.NumberFormat(undefined, {
            style: "currency",
            currency: currency || "USD",
          }).format(amount),
        };
      } catch {
        return { text: String(amount) };
      }
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
