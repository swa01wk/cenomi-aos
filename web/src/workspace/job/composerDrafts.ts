const drafts = new Map<string, string>();

export function getComposerDraft(instanceId: string): string {
  return drafts.get(instanceId) ?? "";
}

export function setComposerDraft(instanceId: string, text: string): void {
  if (text) drafts.set(instanceId, text);
  else drafts.delete(instanceId);
}

export function clearComposerDraft(instanceId: string): void {
  drafts.delete(instanceId);
}
