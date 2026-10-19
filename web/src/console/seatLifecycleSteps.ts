import type { components } from "../api/schema";
import type { LifecycleStep } from "../components";

type SeatState = components["schemas"]["SeatState"];
type HistoryEntry = NonNullable<components["schemas"]["SeatDetail"]["history"]>[number];

const LIFECYCLE_ORDER: SeatState[] = ["DRAFT", "CONFIGURED", "TESTING", "APPROVED", "ACTIVE"];

function latestTransitionTo(
  history: HistoryEntry[] | undefined,
  state: SeatState,
): HistoryEntry | undefined {
  if (!history?.length) return undefined;
  let best: HistoryEntry | undefined;
  for (const h of history) {
    if (h.to !== state) continue;
    if (!best || (h.at && (!best.at || h.at > best.at))) best = h;
  }
  return best;
}

function reached(history: HistoryEntry[] | undefined, state: SeatState): boolean {
  if (latestTransitionTo(history, state)) return true;
  return Boolean(history?.some((h) => h.from === state));
}

export function buildSeatLifecycleSteps(
  state: SeatState,
  history: HistoryEntry[] | undefined,
  formatMeta: (entry: HistoryEntry) => string | undefined,
): LifecycleStep[] {
  const inMainPath = LIFECYCLE_ORDER.includes(state);

  return LIFECYCLE_ORDER.map((stepState) => {
    const transition = latestTransitionTo(history, stepState);
    const meta = transition ? formatMeta(transition) : undefined;

    if (inMainPath) {
      const currentIdx = LIFECYCLE_ORDER.indexOf(state);
      const stepIdx = LIFECYCLE_ORDER.indexOf(stepState);
      const status = stepIdx < currentIdx ? "done" : stepIdx === currentIdx ? "current" : "next";
      return { state: stepState, status, meta };
    }

    const status = reached(history, stepState) ? "done" : "next";
    return { state: stepState, status, meta };
  });
}
