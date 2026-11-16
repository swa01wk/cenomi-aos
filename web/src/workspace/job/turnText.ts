import type { Turn } from "../../components/types";

export function turnPlainText(turn: Turn): string {
  return turn.blocks
    .flatMap((b) => (b.kind === "text" ? [b.text] : []))
    .join("\n")
    .trim();
}

/** One-line excerpt for a quoted reply preview (Google Chat style). */
export function turnQuoteExcerpt(turn: Turn, maxLen = 200): string {
  const flat = turnPlainText(turn).replace(/\s+/g, " ").trim();
  if (!flat) return "";
  if (flat.length <= maxLen) return flat;
  return `${flat.slice(0, maxLen - 1)}…`;
}
