import type { components } from "../../../api/schema";
import { downloadDocumentPdf, masterRfpPdfFileStem } from "./downloadDocumentPdf";
import styles from "./views.module.css";

type ArtifactView = components["schemas"]["ArtifactView"];

export function downloadMasterRfpPdf(view: ArtifactView, content: Record<string, unknown>): void {
  downloadDocumentPdf({
    view,
    content,
    documentHeading: "Master RFP",
    fileStem: masterRfpPdfFileStem(content),
  });
}

export function DocumentPdfDownload({
  view,
  content,
  artifactType,
}: {
  view: ArtifactView;
  content: Record<string, unknown>;
  artifactType: string;
}) {
  if (artifactType !== "master_rfp") {
    return null;
  }

  const onDownload = () => downloadMasterRfpPdf(view, content);

  return (
    <div className={styles.docToolbar}>
      <button type="button" className="btn" onClick={onDownload}>
        Download PDF
      </button>
    </div>
  );
}
