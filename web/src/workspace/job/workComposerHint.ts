import type { InstanceSnapshot } from "./jobStreamReducer";

type ArtifactSummary = InstanceSnapshot["artifacts"][number];

export function messageComposerArtifacts(artifacts: ArtifactSummary[]): ArtifactSummary[] {
  return artifacts.filter((a) => a.view.type === "message_composer");
}

export function composerHintStorageKey(instanceId: string, artifacts: ArtifactSummary[]): string {
  const sig = messageComposerArtifacts(artifacts)
    .map((a) => `${a.artifact_id}@${a.latest_version}`)
    .sort()
    .join("|");
  return `aos:composer-hint:${instanceId}:${sig}`;
}

export function composerHintDismissed(key: string): boolean {
  try {
    return sessionStorage.getItem(key) === "1";
  } catch {
    return false;
  }
}

export function dismissComposerHint(key: string): void {
  try {
    sessionStorage.setItem(key, "1");
  } catch {
    /* ignore */
  }
}

export function composerHintCopy(count: number, stageLabel: string | undefined, instanceState?: string): string {
  const noun = count === 1 ? "A draft outbound message is" : `${count} draft outbound messages are`;
  const action = count === 1 ? "Open the highlighted tab to review it" : "Open the highlighted tabs to review them";
  const stage = stageLabel ? ` (${stageLabel})` : "";
  const send =
    instanceState === "rfq_sending"
      ? " When you are satisfied, use Approve and send below."
      : " Review before sending.";
  return `${noun} ready${stage}. ${action}.${send}`;
}
