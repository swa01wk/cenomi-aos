import type { ComponentType } from "react";
import type { components } from "../../../api/schema";
import { DocumentView } from "./DocumentView";
import { EditableDocumentView } from "./EditableDocumentView";
import { FieldListView } from "./FieldListView";
import { MessageComposerView } from "./MessageComposerView";
import type { InstanceSnapshot } from "../jobStreamReducer";
import { EvalSheetView } from "./EvalSheetView";
import { SheetView } from "./SheetView";
import { SpecStageCallout } from "./SpecStageCallout";

const EVAL_SHEET_TYPES = new Set([
  "rfp_eval_technical",
  "rfp_eval_commercial",
  "quote_eval_technical",
  "quote_eval_commercial",
]);

type ArtifactView = components["schemas"]["ArtifactView"];
type ArtifactVersion = components["schemas"]["ArtifactVersion"];

export type ArtifactViewComponentProps = {
  view: ArtifactView;
  version: ArtifactVersion;
  artifactId?: string;
  artifactType?: string;
  artifactStatus?: string;
  latestVersion?: number;
  canEdit?: boolean;
  onSave?: (content: Record<string, unknown>) => Promise<void>;
  snapshot?: InstanceSnapshot;
};

function SheetViewEntry(props: ArtifactViewComponentProps) {
  const t = props.version.artifact_type ?? "";
  if (EVAL_SHEET_TYPES.has(t)) {
    return <EvalSheetView {...props} />;
  }
  return (
    <>
      <SpecStageCallout artifactType={t} />
      <SheetView view={props.view} version={props.version} />
    </>
  );
}

function DocumentViewEntry(props: ArtifactViewComponentProps) {
  if (props.canEdit && props.onSave) {
    return (
      <EditableDocumentView
        view={props.view}
        version={props.version}
        onSave={props.onSave}
        artifactType={props.version.artifact_type}
      />
    );
  }
  const t = props.version.artifact_type;
  return (
    <>
      <SpecStageCallout artifactType={t} />
      <DocumentView view={props.view} version={props.version} artifactType={t} />
    </>
  );
}

const registry: Record<string, ComponentType<ArtifactViewComponentProps>> = {
  document: DocumentViewEntry,
  sheet: SheetViewEntry,
  message_composer: MessageComposerView,
};

export function artifactViewComponent(viewType: string): ComponentType<ArtifactViewComponentProps> {
  return registry[viewType] ?? FieldListView;
}
