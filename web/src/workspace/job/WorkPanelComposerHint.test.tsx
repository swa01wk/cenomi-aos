import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { InstanceSnapshot } from "./jobStreamReducer";
import { WorkPanelComposerHint } from "./WorkPanelComposerHint";

const base: InstanceSnapshot = {
  instance_id: "QQ-1",
  title: "Job",
  workflow: "quick_quote",
  pack_version: "p@1",
  state: "rfq_drafting",
  version: 3,
  stages: [{ state: "rfq_drafting", label: "RFQ drafting", status: "current" }],
  participants: [],
  my_roles: ["buyer"],
  pending: [],
  artifacts: [
    {
      artifact_id: "art-mail",
      artifact_type: "rfq_email",
      name: "Rfq Email SUP-1",
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
