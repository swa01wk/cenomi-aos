import type { ComponentType } from "react";
import type { components } from "../../../api/schema";
import { DocumentView } from "./DocumentView";
import { EditableDocumentView } from "./EditableDocumentView";
import { FieldListView } from "./FieldListView";
import { MessageComposerView } from "./MessageComposerView";
import { SheetView } from "./SheetView";

type ArtifactView = components["schemas"]["ArtifactView"];
type ArtifactVersion = components["schemas"]["ArtifactVersion"];

export type ArtifactViewComponentProps = {
  view: ArtifactView;
  version: ArtifactVersion;
  artifactId?: string;
  artifactStatus?: string;
  latestVersion?: number;
  canEdit?: boolean;
  onSave?: (content: Record<string, unknown>) => Promise<void>;
};

function DocumentViewEntry(props: ArtifactViewComponentProps) {
  if (props.canEdit && props.onSave) {
    return <EditableDocumentView view={props.view} version={props.version} onSave={props.onSave} />;
  }
  return <DocumentView view={props.view} version={props.version} />;
}

const registry: Record<string, ComponentType<ArtifactViewComponentProps>> = {
  document: DocumentViewEntry,
  sheet: SheetView,
  message_composer: MessageComposerView,
};

export function artifactViewComponent(viewType: string): ComponentType<ArtifactViewComponentProps> {
  return registry[viewType] ?? FieldListView;
}
