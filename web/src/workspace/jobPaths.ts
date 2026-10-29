export function personChatPath(seat: string, instanceId: string): string {
  return `/workspace/people/${encodeURIComponent(seat)}/${encodeURIComponent(instanceId)}`;
}

export function jobDetailPath(instanceId: string): string {
  return `/workspace/jobs/${encodeURIComponent(instanceId)}`;
}
