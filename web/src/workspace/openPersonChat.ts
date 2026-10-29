import type { components } from "../api/schema";
import { isEntryColleague } from "./workspaceEntry";

type Job = components["schemas"]["InstanceSummary"];

const HANDED_OFF_KEY = "aos:coordinator-handed-off";

function activityMs(j: Job): number {
  return new Date(j.last_activity_at ?? j.started_at ?? 0).getTime();
}

function handedOffIds(): Set<string> {
  try {
    const raw = sessionStorage.getItem(HANDED_OFF_KEY);
    if (!raw) return new Set();
    const parsed = JSON.parse(raw) as unknown;
    if (!Array.isArray(parsed)) return new Set();
    return new Set(parsed.filter((x): x is string => typeof x === "string"));
  } catch {
    return new Set();
  }
}

/** Remember a coordinator thread we handed off so People opens a fresh chat next time. */
export function markCoordinatorHandedOff(instanceId: string): void {
  const next = new Set(handedOffIds());
  next.add(instanceId);
  const list = [...next].slice(-30);
  sessionStorage.setItem(HANDED_OFF_KEY, JSON.stringify(list));
}

type Worker = components["schemas"]["DigitalWorker"];

/** Open DM thread for this colleague, if one exists. */
export function openChatInstanceForSeat(seat: string, jobs: Job[], worker: Worker): string | undefined {
  const open = jobs.filter((j) => j.seat === seat && !j.closed_at);
  const sorted = [...open].sort((a, b) => activityMs(b) - activityMs(a));
  const skip = handedOffIds();

  if (isEntryColleague(worker)) {
    const chat = sorted.find(
      (j) => j.workflow === "workspace_coordination" && j.state === "chat" && !skip.has(j.instance_id),
    );
    return chat?.instance_id;
  }

  const conversational = sorted.find(
    (j) => j.workflow !== "workspace_coordination" && (j.state === "conversation" || j.state === "intake"),
  );
  if (conversational) return conversational.instance_id;
  return sorted[0]?.instance_id;
}
