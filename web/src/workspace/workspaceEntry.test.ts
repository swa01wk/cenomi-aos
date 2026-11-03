import { describe, expect, it } from "vitest";
import {
  bestSpecialistIntakeMessage,
  buildHandoffIntakeMessage,
  entryColleague,
  isCoordinatorJob,
  isEntryColleague,
  isSmallTalk,
  pickSpecialistWorker,
  routeWorkflowName,
  routingScore,
  shouldHandOffFromCoordinator,
  shouldOpenSpecialistJob,
} from "./workspaceEntry";
import type { components } from "../api/schema";

type Worker = components["schemas"]["DigitalWorker"];

const entry: Worker = {
  seat: "seat_entry",
  display_name: "Sam Taylor",
  colleague_name: "Sam Taylor",
  title: "Workspace coordinator",
  version: 1,
  state: "ACTIVE",
  workflows: [{ name: "coord", title: "Coordination", description: "First line", intake_hints: [] }],
};

const specialist: Worker = {
  seat: "seat_spec",
  display_name: "Noor",
  colleague_name: "Noor Al-Rashid",
  title: "Specialist",
  version: 1,
  state: "ACTIVE",
  workflows: [
    {
      name: "qq",
      title: "Quick Quote",
      description: "Find suppliers",
      intake_hints: ["equipment", "need", "laptop"],
    },
  ],
};

describe("workspaceEntry", () => {
  it("does not treat a new quick quote as coordinator chat", () => {
    expect(
      isCoordinatorJob({
        workflow: "quick_quote",
        state: "conversation",
        artifacts: [],
        stages: [{ state: "conversation" }],
      }),
    ).toBe(false);
    expect(
      isCoordinatorJob({
        workflow: "workspace_coordination",
        state: "chat",
        artifacts: [],
        stages: [{ state: "chat" }],
      }),
    ).toBe(true);
  });

  it("identifies the entry colleague", () => {
    expect(isEntryColleague(entry)).toBe(true);
    expect(isEntryColleague(specialist)).toBe(false);
    expect(entryColleague([specialist, entry])?.seat).toBe("seat_entry");
  });

  it("scores routing for specialist intake", () => {
    const workers = [entry, specialist];
    expect(routingScore("hi", workers)).toBe(0);
    expect(shouldOpenSpecialistJob("hi", workers)).toBe(false);
    expect(shouldOpenSpecialistJob("We need equipment for the site", workers)).toBe(true);
    expect(pickSpecialistWorker("We need laptops for the site", workers)?.seat).toBe("seat_spec");
  });

  it("treats greetings as small talk", () => {
    expect(isSmallTalk("hey")).toBe(true);
    expect(isSmallTalk("hey sourcing agent how are you?")).toBe(true);
    expect(isSmallTalk("I need 15 macbooks m4 air before the 20th")).toBe(false);
  });

  it("hands off when detail appeared earlier in the coordinator thread", () => {
    const workers = [entry, specialist];
    const snap = { workflow: "workspace_coordination", state: "chat" };
    const turns = [
      {
        turn_id: "1",
        seq: 1,
        at: "2026-10-29T08:00:00Z",
        author: { kind: "person" as const, id: "p", name: "F" },
        blocks: [{ kind: "text" as const, text: "We need 20 laptops for the mall" }],
      },
    ];
    expect(shouldHandOffFromCoordinator(snap, "no special brand", turns, workers)).toBe(true);
    expect(bestSpecialistIntakeMessage("no", ["We need 20 laptops for the mall"], workers)).toBe(
      "We need 20 laptops for the mall",
    );
    expect(buildHandoffIntakeMessage("no", turns, workers)).toBe("We need 20 laptops for the mall");
  });

  it("handoff sends only the intent line, not the whole coordinator thread", () => {
    const workers = [entry, specialist];
    const turns = [
      {
        turn_id: "1",
        seq: 1,
        at: "2026-10-29T08:00:00Z",
        author: { kind: "person" as const, id: "p", name: "F" },
        blocks: [{ kind: "text" as const, text: "Hey, how are you?" }],
      },
      {
        turn_id: "2",
        seq: 2,
        at: "2026-10-29T08:01:00Z",
        author: { kind: "person" as const, id: "p", name: "F" },
        blocks: [{ kind: "text" as const, text: "hey broooo" }],
      },
    ];
    expect(buildHandoffIntakeMessage("i need 10 macs", turns, workers)).toBe("i need 10 macs");
  });

  it("routes website RFP wording to sourcing_rfp", () => {
    const workers: Worker[] = [
      entry,
      {
        ...specialist,
        workflows: [
          { name: "quick_quote", title: "Quick Quote", description: "Quotes", intake_hints: ["need", "quote"] },
          {
            name: "sourcing_rfp",
            title: "Sourcing event (full RFP)",
            description: "Formal RFP",
            intake_hints: ["rfp", "website", "software"],
          },
        ],
      },
    ];
    expect(routeWorkflowName("I need to create an RFP for website redesign", workers)).toBe("sourcing_rfp");
  });
});
