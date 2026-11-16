import { describe, expect, it } from "vitest";
import { bulkReplyDraft, questionsInAgentTurn } from "./agentReplyTemplate";
import type { Turn } from "../../components/types";

function seatTurn(blocks: Turn["blocks"]): Turn {
  return {
    turn_id: "t1",
    seq: 1,
    at: "2026-11-02T12:00:00Z",
    author: { kind: "seat", id: "seat", name: "Noor" },
    blocks,
  };
}

describe("questionsInAgentTurn", () => {
  it("reads separate ask_question blocks after a preamble", () => {
    const turn = seatTurn([
      { kind: "text", text: "I need a few details:" },
      { kind: "text", text: "Delivery date and place?" },
      { kind: "text", text: "Any budget guidance?" },
      { kind: "text", text: "Who signs off on quality?" },
    ]);
    expect(questionsInAgentTurn(turn)).toEqual([
      "Delivery date and place?",
      "Any budget guidance?",
      "Who signs off on quality?",
    ]);
  });

  it("reads a numbered list in one block", () => {
    const turn = seatTurn([
      {
        kind: "text",
        text: "Please confirm:\n1. Delivery date\n2. Site name\n3. Sign-off owner\n4. Reply window\n5. Quantity check",
      },
    ]);
    expect(questionsInAgentTurn(turn)).toHaveLength(5);
  });
});

describe("bulkReplyDraft", () => {
  it("builds numbered answer lines", () => {
    expect(
      bulkReplyDraft(["Delivery date?", "Budget?"]),
    ).toBe("1. Delivery date: \n2. Budget: ");
  });
});
