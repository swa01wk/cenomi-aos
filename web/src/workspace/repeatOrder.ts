/** Default first message when starting a job as a repeat of a closed one. */
export function repeatOrderFirstMessage(sourceInstanceId: string, userNote: string): string {
  const note = userNote.trim();
  const lead = `Repeat the order from ${sourceInstanceId}. Same items and specification as that job unless I say otherwise below.`;
  return note ? `${lead}\n\n${note}` : `${lead}\n\nUpdate the delivery date if needed.`;
}
