import type { Turn } from "../../components/types";

function textLines(turn: Turn): string[] {
  return turn.blocks
    .flatMap((b) => (b.kind === "text" ? [b.text.trim()] : []))
    .filter((t) => t.length > 0);
}

/** Lines like "1. Delivery date" or "2) Budget" */
function numberedListItems(text: string): string[] {
  const lines = text.split(/\n+/).map((l) => l.trim()).filter(Boolean);
  const items: string[] = [];
  for (const line of lines) {
    const m = line.match(/^\d+[.)]\s*(.+)$/);
    if (m) items.push(m[1]!.trim());
  }
  return items;
}

/** Questions the agent asked in one turn (for a single combined reply). */
export function questionsInAgentTurn(turn: Turn): string[] {
  if (turn.author.kind === "person") return [];
  const texts = textLines(turn);
  if (!texts.length) return [];

  const fromNumbered = numberedListItems(texts.join("\n"));
  if (fromNumbered.length >= 2) return fromNumbered;

  const explicit = texts.filter((t) => t.endsWith("?"));
  if (explicit.length >= 2) return explicit;

  if (texts.length >= 2) {
    const rest = texts.slice(1);
    if (rest.length >= 2 && rest.every((t) => t.length <= 280)) return rest;
  }

  if (explicit.length === 1) return explicit;
  return [];
}

export function agentTurnHasQuestionBundle(turn: Turn): boolean {
  return questionsInAgentTurn(turn).length >= 2;
}

/** Prefill the composer so the user can answer every question in one send. */
export function bulkReplyDraft(questions: string[]): string {
  if (questions.length < 2) return "";
  return questions
    .map((q, i) => {
      const label = q.replace(/\?+$/, "").trim();
      return `${i + 1}. ${label}: `;
    })
    .join("\n");
}

export function lastAgentTurn(turns: Turn[]): Turn | undefined {
  for (let i = turns.length - 1; i >= 0; i -= 1) {
    const t = turns[i]!;
    if (t.author.kind === "seat") return t;
  }
  return undefined;
}
