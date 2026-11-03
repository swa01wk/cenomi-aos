import { describe, expect, it } from "vitest";
import { specialistChatTurns } from "./conversationDisplay";
import type { InstanceSnapshot } from "./jobStreamReducer";

function snap(partial: Partial<InstanceSnapshot>): InstanceSnapshot {
  return {
    instance_id: "QQ-1",
    title: "T",
    workflow: "quick_quote",
    seat: "seat_sourcing_poc",
    assignee: { kind: "seat", id: "seat", name: "Noor" },
    pack_version: "pv",
    state: "intake",
    version: 1,
    stages: [],
    participants: [],
    my_roles: ["requester"],
    pending: [],
    artifacts: [],
    turns: [],
    cursor: "",
    ...partial,
  } as InstanceSnapshot;
}

describe("specialistChatTurns", () => {
  it("hides older person lines before brief v1 but keeps the latest person message", () => {
    const turns = [
      {
        turn_id: "1",
        seq: 1,
        at: "2026-10-29T08:00:00Z",
        author: { kind: "person" as const, id: "faisal", name: "Faisal" },
        blocks: [{ kind: "text" as const, text: "i need macs" }],
      },
      {
        turn_id: "2",
        seq: 2,
        at: "2026-10-29T08:02:00Z",
        author: { kind: "person" as const, id: "faisal", name: "Faisal" },
        blocks: [{ kind: "text" as const, text: "I need 14 macs" }],
      },
    ];
    const snapshot = snap({
      artifacts: [
        {
          artifact_id: "b1",
          artifact_type: "brief",
          name: "Brief",
          latest_version: 1,
          status: "draft",
          view: { type: "document", fields: [] },
          versions: [{ version: 1, by: "worker", at: "2026-10-29T08:04:00Z" }],
        },
      ],
      turns,
    });
    const visible = specialistChatTurns(snapshot, turns);
    expect(visible.map((t) => t.turn_id)).toEqual(["2"]);
  });

  it("keeps the only person turn even when it is before the brief timestamp (handoff seed)", () => {
    const turns = [
      {
        turn_id: "seed",
        seq: 1,
        at: "2026-10-29T08:00:00Z",
        author: { kind: "person" as const, id: "faisal", name: "Faisal" },
        blocks: [{ kind: "text" as const, text: "I need 14 macs" }],
      },
    ];
    const snapshot = snap({
      artifacts: [
        {
          artifact_id: "b1",
          artifact_type: "brief",
          name: "Brief",
          latest_version: 1,
          status: "draft",
          view: { type: "document", fields: [] },
          versions: [{ version: 1, by: "worker", at: "2026-10-29T08:05:00Z" }],
        },
      ],
      turns,
    });
    const visible = specialistChatTurns(snapshot, turns);
    expect(visible.map((t) => t.turn_id)).toEqual(["seed"]);
  });

  it("hides the requester thread and pre-brief seat lines for the buyer", () => {
    const turns = [
      {
        turn_id: "s1",
        seq: 1,
        at: "2026-11-02T07:00:00Z",
        author: { kind: "seat" as const, id: "seat_sourcing_poc", name: "Noor" },
        blocks: [{ kind: "text" as const, text: "How many?" }],
      },
      {
        turn_id: "f1",
        seq: 2,
        at: "2026-11-02T07:01:00Z",
        author: { kind: "person" as const, id: "faisal", name: "Faisal" },
        blocks: [{ kind: "text" as const, text: "12 iphones" }],
      },
      {
        turn_id: "f2",
        seq: 3,
        at: "2026-11-02T07:02:00Z",
        author: { kind: "person" as const, id: "faisal", name: "Faisal" },
        blocks: [{ kind: "text" as const, text: "confirm this" }],
      },
      {
        turn_id: "n1",
        seq: 4,
        at: "2026-11-02T07:10:00Z",
        author: { kind: "person" as const, id: "noura", name: "Noura" },
        blocks: [{ kind: "text" as const, text: "Approved." }],
      },
    ];
    const snapshot = snap({
      state: "shortlisting",
      my_roles: ["buyer"],
      participants: [
        { role: "requester", person_id: "faisal", name: "Faisal", bound_by: "creation" },
        { role: "buyer", person_id: "noura", name: "Noura", bound_by: "claim" },
      ],
      artifacts: [
        {
          artifact_id: "b1",
          artifact_type: "brief",
          name: "Brief",
          latest_version: 1,
          status: "draft",
          view: { type: "document", fields: [] },
          versions: [{ version: 1, by: "worker", at: "2026-11-02T07:05:00Z" }],
        },
      ],
      turns,
    });
    const visible = specialistChatTurns(snapshot, turns);
    expect(visible.map((t) => t.turn_id)).toEqual(["n1"]);
  });
});
