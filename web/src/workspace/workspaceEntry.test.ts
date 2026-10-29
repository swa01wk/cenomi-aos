import { describe, expect, it } from "vitest";
import {
  bestSpecialistIntakeMessage,
  buildHandoffIntakeMessage,
  entryColleague,
  isEntryColleague,
  isSmallTalk,
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
    expect(buildHandoffIntakeMessage("no", turns, workers)).toContain("20 laptops");
  });
});
