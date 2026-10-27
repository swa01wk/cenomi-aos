import type { ComponentType } from "react";
import type { components } from "../../../api/schema";
import { DocumentView } from "./DocumentView";
import { FieldListView } from "./FieldListView";
import { SheetView } from "./SheetView";

type ArtifactView = components["schemas"]["ArtifactView"];
type ArtifactVersion = components["schemas"]["ArtifactVersion"];

export type ArtifactViewComponentProps = {
  view: ArtifactView;
  version: ArtifactVersion;
};

const registry: Record<string, ComponentType<ArtifactViewComponentProps>> = {
  document: DocumentView,
  sheet: SheetView,
};

export function artifactViewComponent(viewType: string): ComponentType<ArtifactViewComponentProps> {
  return registry[viewType] ?? FieldListView;
}
