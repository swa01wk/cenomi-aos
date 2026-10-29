import type { components } from "../api/schema";

type Worker = components["schemas"]["DigitalWorker"];
type Assignee = components["schemas"]["JobAssignee"];

export function workerColleagueName(worker: Pick<Worker, "colleague_name" | "display_name">): string {
  return worker.colleague_name?.trim() || worker.display_name;
}

export function workerInitials(worker: Pick<Worker, "colleague_name" | "display_name" | "persona">): string {
  const persona = worker.persona;
  if (persona?.given_name) {
    const g = persona.given_name[0] ?? "";
    const f = persona.family_name?.[0] ?? "";
    return (g + f).toUpperCase() || "?";
  }
  const name = workerColleagueName(worker);
  const parts = name.split(/\s+/).filter(Boolean);
  if (parts.length >= 2) return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
  return (name[0] ?? "?").toUpperCase();
}

export function assigneeLabel(assignee: Assignee | undefined): { name: string; title: string } {
  if (!assignee) return { name: "Colleague", title: "" };
  return { name: assignee.colleague_name, title: assignee.title ?? "" };
}
