import { describe, expect, it } from "vitest";
import { composerHintCopy, messageComposerArtifacts } from "./workComposerHint";
import type { InstanceSnapshot } from "./jobStreamReducer";

function artifact(id: string, viewType: string): InstanceSnapshot["artifacts"][number] {
  return {
    artifact_id: id,
    artifact_type: "x",
    name: "Draft",
    latest_version: 1,
    status: "draft",
    view: { type: viewType as "message_composer", fields: [] },
  };
}

describe("workComposerHint", () => {
  it("finds message_composer artifacts only", () => {
    const list = messageComposerArtifacts([artifact("a", "sheet"), artifact("b", "message_composer")]);
    expect(list.map((a) => a.artifact_id)).toEqual(["b"]);
  });

  it("writes copy for one or many drafts", () => {
    expect(composerHintCopy(1, "Outbound drafting")).toContain("A draft outbound message is ready");
    expect(composerHintCopy(3, undefined)).toContain("3 draft outbound messages are ready");
    expect(composerHintCopy(2, "Outbound sending", "rfq_sending")).toContain("Approve and send");
  });
});
