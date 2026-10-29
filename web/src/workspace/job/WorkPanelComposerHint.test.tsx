import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { TEST_SNAPSHOT_SHELL, TEST_WORKFLOW } from "../testJobFixtures";
import type { InstanceSnapshot } from "./jobStreamReducer";
import { WorkPanelComposerHint } from "./WorkPanelComposerHint";

const base: InstanceSnapshot = {
  ...TEST_SNAPSHOT_SHELL,
  instance_id: "QQ-1",
  title: "Job",
  workflow: TEST_WORKFLOW,
  pack_version: "p@1",
  state: "rfq_drafting",
  version: 3,
  stages: [{ state: "rfq_drafting", label: "Outbound drafting", status: "current" }],
  participants: [],
  my_roles: ["buyer"],
  pending: [],
  artifacts: [
    {
      artifact_id: "art-mail",
      artifact_type: "type_outbound",
      name: "Outbound draft A",
      latest_version: 2,
      status: "draft",
      view: { type: "message_composer", fields: [] },
    },
  ],
  turns: [],
  cursor: "instance:QQ-1:0",
};

describe("WorkPanelComposerHint", () => {
  afterEach(() => {
    cleanup();
    sessionStorage.clear();
  });

  it("shows the ready banner until the user opens a draft tab", () => {
    render(
      <WorkPanelComposerHint
        instanceId="QQ-1"
        snapshot={base}
        activeArtifactId="other"
        onOpenDraft={vi.fn()}
      />,
    );
    expect(screen.getByRole("status")).toHaveTextContent(/draft outbound message.*ready/i);
    expect(screen.getByRole("button", { name: "Open draft" })).toBeInTheDocument();
  });

  it("hides after dismiss", () => {
    render(
      <WorkPanelComposerHint
        instanceId="QQ-1"
        snapshot={base}
        activeArtifactId="other"
        onOpenDraft={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    expect(screen.queryByRole("status")).toBeNull();
  });
});
