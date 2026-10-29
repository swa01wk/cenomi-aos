import type { components } from "../api/schema";

type Worker = components["schemas"]["DigitalWorker"];
type Workflow = Worker["workflows"][number];
type Turn = components["schemas"]["Turn"];

const TOKEN = /[a-z0-9']+/gi;

function hintScore(message: string, hints: string[]): number {
  if (!hints.length) return 0;
  const lower = message.toLowerCase();
  const tokens = new Set(lower.match(TOKEN) ?? []);
  let score = 0;
  for (const raw of hints) {
    const hint = raw.toLowerCase().trim();
    if (!hint) continue;
    if (hint.includes(" ")) {
      if (lower.includes(hint)) score += 2;
    } else if (tokens.has(hint) || lower.includes(hint)) {
      score += 1;
    }
  }
  return score;
}

function fieldScore(message: string, ...fields: string[]): number {
  const lower = message.toLowerCase();
  const tokens = new Set(lower.match(TOKEN) ?? []);
  let score = 0;
  for (const field of fields) {
    for (const word of field.toLowerCase().match(TOKEN) ?? []) {
      if (word.length < 3) continue;
      if (tokens.has(word) || lower.includes(word)) score += 1;
    }
  }
  return score;
}

export function routableWorkflows(worker: Worker): Workflow[] {
  return worker.workflows.filter((w) => (w.intake_hints?.length ?? 0) > 0);
}

/** Colleague shown on Messages / New job — only routes requests, not specialist seats. */
export function isEntryColleague(worker: Worker): boolean {
  return worker.workflows.length > 0 && worker.workflows.every((w) => !(w.intake_hints?.length ?? 0));
}

export function entryColleague(workers: Worker[]): Worker | undefined {
  return workers.find(isEntryColleague);
}

export function specialistColleagues(workers: Worker[]): Worker[] {
  return workers.filter((w) => routableWorkflows(w).length > 0);
}

export function routingScore(message: string, workers: Worker[]): number {
  let best = 0;
  for (const worker of specialistColleagues(workers)) {
    for (const wf of routableWorkflows(worker)) {
      const hints = wf.intake_hints ?? [];
      best = Math.max(
        best,
        hintScore(message, hints) + fieldScore(message, wf.title ?? "", wf.description ?? ""),
      );
    }
  }
  return best;
}

/** True when the message looks like a concrete request worth opening a specialist job. */
export function shouldOpenSpecialistJob(message: string, workers: Worker[]): boolean {
  return routingScore(message, workers) >= 1;
}

export function personTurnTexts(turns: Turn[]): string[] {
  return turns
    .filter((t) => t.author.kind === "person")
    .map((t) =>
      (t.blocks ?? [])
        .flatMap((b) => (b.kind === "text" ? [b.text] : []))
        .join(" ")
        .trim(),
    )
    .filter(Boolean);
}

/** Best person message to seed a specialist job (current turn or earlier detail in the thread). */
export function bestSpecialistIntakeMessage(latestText: string, priorPersonTexts: string[], workers: Worker[]): string | null {
  const trimmed = latestText.trim();
  if (trimmed && shouldOpenSpecialistJob(trimmed, workers)) return trimmed;
  for (let i = priorPersonTexts.length - 1; i >= 0; i--) {
    const t = priorPersonTexts[i]!;
    if (shouldOpenSpecialistJob(t, workers)) return t;
  }
  return null;
}

/** Combine recent person lines so the specialist sees coordinator context. */
export function buildHandoffIntakeMessage(latestText: string, turns: Turn[], workers: Worker[]): string {
  const prior = personTurnTexts(turns);
  const anchor = bestSpecialistIntakeMessage(latestText, prior, workers);
  const parts = [...prior, latestText.trim()].filter(Boolean);
  const unique: string[] = [];
  for (const p of parts) {
    if (!unique.includes(p)) unique.push(p);
  }
  if (!anchor) return latestText.trim();
  if (unique.length <= 1) return anchor;
  return unique.slice(-5).join(" · ");
}

/** Coordinator chat: hand off once we have ever heard a concrete request in this thread. */
export function shouldHandOffFromCoordinator(
  snapshot: { workflow: string; state: string },
  latestText: string,
  turns: Turn[],
  workers: Worker[],
): boolean {
  if (snapshot.workflow !== "workspace_coordination" || snapshot.state !== "chat") return false;
  const prior = personTurnTexts(turns);
  return bestSpecialistIntakeMessage(latestText, prior, workers) !== null;
}

/** Greeting or small talk: stay in conversation, do not show brief-drafting progress. */
export function isSmallTalk(text: string): boolean {
  const t = text.trim();
  if (!t) return true;
  if (t.length > 80 || /\d/.test(t)) return false;
  return t.split(/\s+/).filter(Boolean).length <= 8;
}

export function coordinationWorkflow(worker: Worker): Workflow | undefined {
  return worker.workflows[0];
}

/** Coordinator threads have no work artifacts yet (chat-only workflow). */
export function isCoordinatorJob(snapshot: {
  artifacts: unknown[];
  stages: { state: string }[];
  workflow?: string;
  state?: string;
}): boolean {
  if (snapshot.workflow === "workspace_coordination") {
    return snapshot.state === "chat";
  }
  return snapshot.artifacts.length === 0 && snapshot.stages.length <= 1;
}
