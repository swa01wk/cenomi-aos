import type { components } from "../api/schema";

type Worker = components["schemas"]["DigitalWorker"];
type Workflow = Worker["workflows"][number];
type Turn = components["schemas"]["Turn"];

const TOKEN = /[a-z0-9']+/gi;

/** Keep in sync with backend intake_routing._RFP_STRONG (formal RFP vs Quick Quote). */
const RFP_STRONG =
  /\b(rfp|tender|proposal|web portal|rest api|master rfp|formal rfp|sourcing event|website redesign|web redesign|marketing website|public website)\b/i;

const WORKFLOW_TIE_PRIORITY: Record<string, number> = { sourcing_rfp: 2, quick_quote: 1 };

export function isFormalRfpRequest(message: string): boolean {
  return RFP_STRONG.test(message);
}

/** Best workflow name for intake routing (mirrors kernel route_intake_message tie-break). */
export function routeWorkflowName(message: string, workers: Worker[]): string | undefined {
  let best: { name: string; score: number; pri: number } | undefined;
  for (const worker of specialistColleagues(workers)) {
    for (const wf of routableWorkflows(worker)) {
      const hints = wf.intake_hints ?? [];
      let score = hintScore(message, hints) + fieldScore(message, wf.title ?? "", wf.description ?? "");
      if (RFP_STRONG.test(message)) {
        if (wf.name === "sourcing_rfp") score += 14;
        else if (wf.name === "quick_quote") score -= 8;
      }
      const pri = WORKFLOW_TIE_PRIORITY[wf.name] ?? 0;
      if (!best || score > best.score || (score === best.score && pri > best.pri)) {
        best = { name: wf.name, score, pri };
      }
    }
  }
  return best?.name;
}

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

function workerRoutingScore(message: string, worker: Worker): number {
  let best = 0;
  for (const wf of routableWorkflows(worker)) {
    const hints = wf.intake_hints ?? [];
    best = Math.max(
      best,
      hintScore(message, hints) + fieldScore(message, wf.title ?? "", wf.description ?? ""),
    );
  }
  return best;
}

/** Best-matching specialist seat for a concrete request (for handoff UX copy). */
export function pickSpecialistWorker(message: string, workers: Worker[]): Worker | undefined {
  const specialists = specialistColleagues(workers);
  if (!specialists.length) return undefined;
  let best: Worker | undefined;
  let bestScore = 0;
  for (const worker of specialists) {
    const score = workerRoutingScore(message, worker);
    if (score > bestScore) {
      bestScore = score;
      best = worker;
    }
  }
  return best ?? specialists[0];
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

/** Single line to seed the specialist job — the intent-classified request only, not coordinator chit-chat. */
export function buildHandoffIntakeMessage(latestText: string, turns: Turn[], workers: Worker[]): string {
  const prior = personTurnTexts(turns);
  const anchor = bestSpecialistIntakeMessage(latestText, prior, workers);
  return anchor ?? latestText.trim();
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

/** Front-desk coordinator thread only — not specialist jobs still waiting on their first artifact. */
export function isCoordinatorJob(snapshot: {
  artifacts: unknown[];
  stages: { state: string }[];
  workflow?: string;
  state?: string;
}): boolean {
  return snapshot.workflow === "workspace_coordination" && snapshot.state === "chat";
}
