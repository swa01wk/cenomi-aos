import styles from "./views.module.css";

const SPEC_INTRO: Record<string, { title: string; detail: string }> = {
  rfp_procurement_validation: {
    title: "Procurement validation",
    detail:
      "Checks the RFP package against procurement conditions: bill of quantities, contract terms, SLAs, scope boundary, and fixed-price model before issue.",
  },
  rfp_template_compliance: {
    title: "Template compliance",
    detail:
      "Required sections for this RFP type — agent draft, user upload, or user-added sections. Missing items are suggested or sent back to the requester for re-upload.",
  },
  scoring_method_agreement: {
    title: "Scoring and comparison (agreed upfront)",
    detail:
      "Requester and procurement lock technical/commercial weights, minimum technical score, and QCBS commercial basis before CDO approval and vendor issue.",
  },
  rfp_upload_manifest: {
    title: "User uploads",
    detail:
      "Requester-supplied BoQ and addenda merged into the master RFP. Procurement can require a re-upload after send-back (configurable 1–2 rounds).",
  },
};

export function SpecStageCallout({ artifactType }: { artifactType?: string }) {
  if (!artifactType) return null;
  const intro = SPEC_INTRO[artifactType];
  if (!intro) return null;
  return (
    <aside className={styles.specStageCallout} aria-label={intro.title}>
      <p className={styles.specStageCalloutTitle}>{intro.title}</p>
      <p className={styles.specStageCalloutDetail}>{intro.detail}</p>
    </aside>
  );
}
