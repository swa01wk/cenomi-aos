import type { components } from "../../../api/schema";
import { FieldListView } from "./FieldListView";
import styles from "./views.module.css";

type ArtifactView = components["schemas"]["ArtifactView"];
type ArtifactVersion = components["schemas"]["ArtifactVersion"];

export function DocumentView({
  view,
  version,
}: {
  view: ArtifactView;
  version: ArtifactVersion;
}) {
  const title = version.content.title != null ? String(version.content.title) : "";
  const bodyView: ArtifactView = {
    ...view,
    fields: view.fields.filter((f) => f.name !== "title"),
    columns: view.columns?.filter((c) => c !== "title"),
  };

  return (
    <div className={styles.viewBody}>
      {title ? <h2 className={styles.docTitle}>{title}</h2> : null}
      <FieldListView view={bodyView} version={version} />
    </div>
  );
}
