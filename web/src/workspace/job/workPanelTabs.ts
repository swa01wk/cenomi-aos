import type { InstanceSnapshot } from "./jobStreamReducer";
import { supplierShortName } from "./supplierDisplayNames";
import { SUPPLIER_QUOTES_TAB_ID } from "./workPanelConstants";

export type WorkTabGroup = "drafts" | "responses" | "documents";

type ArtifactSummary = InstanceSnapshot["artifacts"][number];

export function workTabGroup(artifact: ArtifactSummary): WorkTabGroup {
  if (artifact.artifact_id === SUPPLIER_QUOTES_TAB_ID) return "responses";
  if (artifact.view?.type === "message_composer") return "drafts";
  if (artifact.artifact_type === "bafo_email") return "drafts";
  if (artifact.artifact_type === "quote" || artifact.artifact_type === "proposal") return "responses";
  return "documents";
}

const DOC_TYPE_LABEL: Record<string, string> = {
  brief: "Brief",
  supplier_list: "Shortlist",
  rfp_procurement_validation: "RFP validation",
  rfp_template_compliance: "Template check",
  scoring_method_agreement: "Scoring agreement",
  rfp_upload_manifest: "RFP uploads",
  master_rfp: "Master RFP",
  quote_line_matrix: "Line comparison",
  quote_line_scores: "Line scores",
  quote_eval_commercial: "Commercial eval",
  quote_eval_technical: "Technical eval",
  quote_evaluation: "Weighted eval",
  rfp_module_matrix: "Module comparison",
  rfp_module_scores: "Module scores",
  bafo_email: "BAFO",
  technical_criterion_scores: "Technical rubric",
  commercial_criterion_scores: "Commercial rubric",
  rfp_eval_commercial: "Commercial eval",
  rfp_eval_technical: "Technical eval",
  rfp_evaluation: "Weighted eval",
  po_payload: "Requisition",
  rfq_email: "RFQ",
};

export function workTabShortLabel(artifact: ArtifactSummary): string {
  if (artifact.artifact_id === SUPPLIER_QUOTES_TAB_ID) {
    return artifact.name.replace(/^Supplier quotes/i, "Responses");
  }
  const sid = artifact.key?.trim();
  const short = supplierShortName(sid);
  switch (artifact.artifact_type) {
    case "bafo_email":
      return short ? `BAFO · ${short}` : "BAFO";
    case "rfp_invitation":
      return short ? `Invite · ${short}` : "Invitation";
    case "proposal":
      return short ? `Reply · ${short}` : "Proposal";
    case "quote":
      return short ? `Quote · ${short}` : "Quote";
    default: {
      const fromType = DOC_TYPE_LABEL[artifact.artifact_type];
      if (fromType) return fromType;
      const name = artifact.name.trim();
      if (name.length > 28) return `${name.slice(0, 26)}…`;
      return name;
    }
  }
}

const DOC_TAB_ORDER: Record<string, number> = {
  brief: 10,
  supplier_list: 20,
  rfp_procurement_validation: 25,
  rfp_template_compliance: 26,
  scoring_method_agreement: 27,
  rfp_upload_manifest: 28,
  master_rfp: 30,
  rfp_module_matrix: 40,
  rfp_module_scores: 41,
  technical_criterion_scores: 49,
  commercial_criterion_scores: 49,
  rfp_eval_commercial: 50,
  rfp_eval_technical: 51,
  rfp_evaluation: 52,
  quote_line_matrix: 40,
  quote_eval_commercial: 50,
  quote_eval_technical: 51,
  quote_evaluation: 52,
};

export function sortWorkPanelTabArtifacts(artifacts: ArtifactSummary[]): ArtifactSummary[] {
  return [...artifacts].sort((a, b) => {
    const oa = DOC_TAB_ORDER[a.artifact_type] ?? 500;
    const ob = DOC_TAB_ORDER[b.artifact_type] ?? 500;
    if (oa !== ob) return oa - ob;
    return a.name.localeCompare(b.name);
  });
}

export function filterWorkPanelTabArtifacts(
  artifacts: ArtifactSummary[],
  options: { showSupplierQuotesTab: boolean; hideComposerDraftsInBar: boolean },
): ArtifactSummary[] {
  const hiddenTypes = new Set(["eval_scoring_policy"]);
  return artifacts.filter((a) => {
    if (hiddenTypes.has(a.artifact_type)) return false;
    if (options.showSupplierQuotesTab && a.artifact_type === "proposal") return false;
    if (options.hideComposerDraftsInBar && a.view?.type === "message_composer" && a.status !== "draft") {
      return false;
    }
    return true;
  });
}

export function workTabGroupLabel(group: WorkTabGroup): string {
  switch (group) {
    case "drafts":
      return "Drafts";
    case "responses":
      return "Responses";
    default:
      return "Documents";
  }
}

export function groupWorkTabs(
  tabs: ArtifactSummary[],
): { group: WorkTabGroup; tabs: ArtifactSummary[] }[] {
  const order: WorkTabGroup[] = ["drafts", "responses", "documents"];
  const buckets: Record<WorkTabGroup, ArtifactSummary[]> = {
    drafts: [],
    responses: [],
    documents: [],
  };
  for (const t of tabs) {
    buckets[workTabGroup(t)].push(t);
  }
  return order.filter((g) => buckets[g].length > 0).map((group) => ({ group, tabs: buckets[group]! }));
}
