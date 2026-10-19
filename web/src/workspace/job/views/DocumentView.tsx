import type { components } from "../../../api/schema";
import { FieldListView } from "./FieldListView";
import styles from "./views.module.css";

type ArtifactView = components["schemas"]["ArtifactView"];
type ArtifactVersion = components["schemas"]["ArtifactVersion"];

/** view: document. Fields, labels and order come from the view; no field name is treated specially. */
export function DocumentView({ view, version }: { view: ArtifactView; version: ArtifactVersion }) {
  return (
    <div className={styles.viewBody}>
      <FieldListView view={view} version={version} />
    </div>
  );
}
