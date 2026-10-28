import type { ToolActivity } from "../../components/types";

export function formatElapsed(seconds: number): string {
  if (seconds < 60) return `${seconds}s`;
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}m ${s.toString().padStart(2, "0")}s`;
}

export type WorkStep = {
  label: string;
  status: "done" | "current" | "upcoming";
};

export type AgentWorkStatusModel = {
  headline: string;
  steps: WorkStep[];
  expectation: string | null;
  asyncHint: boolean;
  elapsedSec: number;
};

type Input = {
  workflowState: string;
  toolActivity?: ToolActivity;
  isFirstExchange: boolean;
  elapsedSec: number;
};

function stepsForState(state: string): string[] {
  switch (state) {
    case "intake":
      return ["Reading your request", "Checking categories and specs", "Drafting the brief"];
    case "shortlisting":
      return [
        "Pulling suppliers for your brief",
        "Checking supplier records",
        "Ranking the supplier list",
      ];
    case "rfq_drafting":
      return ["Shortlisting suppliers", "Drafting RFQ emails", "Checking each draft"];
    case "rfq_sending":
      return ["Preparing outbound emails", "Checking recipients", "Ready to send"];
    default:
      return ["Working on this step", "Saving results to the work panel"];
  }
}

function inferStepIndex(state: string, elapsedSec: number, toolLabel: string | undefined): number {
  const lower = (toolLabel ?? "").toLowerCase();
  if (lower.includes("brief") || lower.includes("draft")) return 2;
  if (lower.includes("erp") || lower.includes("categor") || lower.includes("search")) return 1;
  if (lower.includes("supplier") || lower.includes("rank")) return 2;
  if (lower.includes("rfq") || lower.includes("email")) return 1;
  const labels = stepsForState(state);
  if (elapsedSec >= 25) return Math.min(2, labels.length - 1);
  if (elapsedSec >= 10) return Math.min(1, labels.length - 1);
  return 0;
}

function expectationFor(state: string, isFirstExchange: boolean): string | null {
  if (isFirstExchange && state === "intake") {
    return "This usually takes about a minute while the worker gathers details for your brief.";
  }
  if (state === "shortlisting") {
    return "Ranking suppliers often takes up to a minute. New rows appear in the work panel on the right.";
  }
  if (state === "rfq_drafting") {
    return "Draft emails will appear in the work panel as they are saved.";
  }
  return null;
}

export function buildAgentWorkStatus(input: Input): AgentWorkStatusModel {
  const { workflowState, toolActivity, isFirstExchange, elapsedSec } = input;
  const labels = stepsForState(workflowState);
  const currentIndex = inferStepIndex(workflowState, elapsedSec, toolActivity?.label);
  const headline = toolActivity?.label?.trim() || labels[currentIndex] || "Working on your request";
  const steps: WorkStep[] = labels.map((label, i) => ({
    label,
    status: i < currentIndex ? "done" : i === currentIndex ? "current" : "upcoming",
  }));
  return {
    headline,
    steps,
    expectation: expectationFor(workflowState, isFirstExchange),
    asyncHint: elapsedSec >= 20,
    elapsedSec,
  };
}
