import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { client } from "../../../api/client";
import { DataTable } from "../../../components";
import { workspaceKeys } from "../../useWorkspaceQueries";
import type { InstanceSnapshot } from "../jobStreamReducer";
import { SheetView } from "./SheetView";
import type { ArtifactViewComponentProps } from "./index";
import { formatFieldValue } from "./formatFieldValue";
import styles from "./views.module.css";

const EVAL_SUMMARY_TYPES = new Set([
  "rfp_eval_technical",
  "rfp_eval_commercial",
  "quote_eval_technical",
  "quote_eval_commercial",
]);

export function EvalSheetView(props: ArtifactViewComponentProps & { snapshot?: InstanceSnapshot }) {
  const { snapshot, version, view } = props;
  const sheetType = version.artifact_type ?? props.artifactType ?? "";
  const [open, setOpen] = useState(true);
  const envelope = sheetType.includes("technical") ? "technical" : "commercial";
  const criterionType =
    envelope === "technical" ? "technical_criterion_scores" : "commercial_criterion_scores";
  const criterionArt = snapshot?.artifacts.find((a) => a.artifact_type === criterionType);
  const policyArt = snapshot?.artifacts.find((a) => a.artifact_type === "eval_scoring_policy");

  const criterionQuery = useQuery({
    queryKey: workspaceKeys.artifactVersion(criterionArt?.artifact_id ?? "none", criterionArt?.latest_version ?? 1),
    enabled: Boolean(criterionArt?.artifact_id),
    queryFn: async () => {
      const { data, error } = await client.GET("/artifacts/{id}/versions/{version}", {
        params: { path: { id: criterionArt!.artifact_id, version: criterionArt!.latest_version } },
      });
      if (error) throw error;
      return data!;
    },
  });

  const policyQuery = useQuery({
    queryKey: workspaceKeys.artifactVersion(policyArt?.artifact_id ?? "none", policyArt?.latest_version ?? 1),
    enabled: Boolean(policyArt?.artifact_id),
    queryFn: async () => {
      const { data, error } = await client.GET("/artifacts/{id}/versions/{version}", {
        params: { path: { id: policyArt!.artifact_id, version: policyArt!.latest_version } },
      });
      if (error) throw error;
      return data!;
    },
  });

  const criterionContent = criterionQuery.data?.content as { rows?: unknown } | undefined;
  const rows = Array.isArray(criterionContent?.rows)
    ? (criterionContent.rows as Record<string, unknown>[])
    : [];
  const policy = (policyQuery.data?.content ?? {}) as Record<string, unknown>;

  const versionContent = version.content as { rows?: unknown } | undefined;
  const summaryRows = Array.isArray(versionContent?.rows)
    ? (versionContent.rows as Record<string, unknown>[])
    : [];

  const showRubric = snapshot && EVAL_SUMMARY_TYPES.has(sheetType);

  return (
    <div className={styles.evalSheetWrap}>
      {showRubric ? (
        <aside className={styles.specStageCallout} aria-label="Evaluation rubric">
          <p className={styles.specStageCalloutTitle}>Summary vs rubric</p>
          <p className={styles.specStageCalloutDetail}>
            The table below is the panel summary ({envelope === "technical" ? "0–100 technical" : "0–100 commercial"}).
            Each supplier is scored per criterion on a 0–5 scale with PRD weights; contributions sum to that score.
          </p>
        </aside>
      ) : null}
      {showRubric ? (
        <div className={styles.evalRubricSection}>
          {!criterionArt ? (
            <p className={styles.evalRubricMissing}>
              Detailed rubric rows are not on this job yet. Run{" "}
              <code className={styles.evalRubricCode}>make demo-client-full</code> or reopen the job with{" "}
              <code className={styles.evalRubricCode}>AOS_DEMO=1</code> so the kernel can backfill criterion scores.
            </p>
          ) : null}
          <button
            type="button"
            className={styles.evalRubricToggle}
            aria-expanded={open}
            onClick={() => setOpen((v) => !v)}
          >
            {open ? "Hide" : "Show"} scoring rubric and calculation
          </button>
          {open ? (
            <div className={styles.evalRubricPanel}>
              {policyQuery.isLoading || criterionQuery.isLoading ? (
                <p className={styles.hiddenNote}>Loading rubric…</p>
              ) : null}
              {policy.technical_formula ? (
                <section className={styles.evalRubricBlock}>
                  <h4 className={styles.evalRubricHeading}>Policy</h4>
                  <p className={styles.hiddenNote}>
                    Overall split: technical {Number(policy.technical_weight) * 100}% / commercial{" "}
                    {Number(policy.commercial_weight) * 100}%. Minimum technical score:{" "}
                    {String(policy.min_technical_score)}.
                  </p>
                  <p className={styles.hiddenNote}>
                    <strong>0–5 scale:</strong> {String(policy.scale_0_5)}
                  </p>
                  <p className={styles.hiddenNote}>
                    <strong>Technical:</strong> {String(policy.technical_formula)}
                  </p>
                  <p className={styles.hiddenNote}>
                    <strong>Commercial:</strong> {String(policy.commercial_formula)}
                  </p>
                  <p className={styles.hiddenNote}>
                    <strong>Combined:</strong> {String(policy.combined_formula)}
                  </p>
                </section>
              ) : null}
              <section className={styles.evalRubricBlock}>
                <h4 className={styles.evalRubricHeading}>
                  {envelope === "technical" ? "Technical criteria breakdown" : "Commercial criteria breakdown"}
                </h4>
                {envelope === "technical" ? (
                  <p className={styles.hiddenNote}>
                    Each row is one criterion for one supplier. Technical score (0–100) = sum of{" "}
                    <em>contribution_pts</em> for that supplier.
                  </p>
                ) : (
                  <p className={styles.hiddenNote}>
                    Price line uses lowest qualified bid. Other commercial criteria are Procurement assessments.
                    Commercial score (0–100) = sum of <em>contribution_pts</em> per supplier.
                  </p>
                )}
                <RubricTable
                  rows={rows}
                  envelope={envelope}
                  summaryRows={summaryRows}
                />
              </section>
            </div>
          ) : null}
        </div>
      ) : null}
      <SheetView view={view} version={version} />
    </div>
  );
}

function RubricTable({
  rows,
  envelope,
  summaryRows,
}: {
  rows: Record<string, unknown>[];
  envelope: "technical" | "commercial";
  summaryRows: Record<string, unknown>[];
}) {
  if (!rows.length) {
    return <p className={styles.hiddenNote}>Rubric detail is not loaded yet. Refresh the job or re-run demo bootstrap.</p>;
  }
  const cols =
    envelope === "technical"
      ? ["supplier", "criterion", "weight_pct", "score_0_5", "contribution_pts", "evidence"]
      : ["supplier", "criterion", "weight_pct", "score_component", "contribution_pts", "calculation_notes"];

  return (
    <>
      <DataTable
        caption="rubric"
        rows={rows}
        empty={<p className={styles.hiddenNote}>No rubric rows</p>}
        getRowKey={(row) => String(row.line_id ?? `${row.supplier}-${row.criterion}`)}
        columns={cols.map((id) => ({
          id,
          header: id.replace(/_/g, " "),
          align: id.includes("pct") || id.includes("score") || id.includes("contribution") ? "right" : "left",
          render: (row: Record<string, unknown>) =>
            formatFieldValue(
              { name: id, type: id === "evidence" || id.includes("notes") ? "text" : "string", label: id },
              row[id],
            ).text,
        }))}
      />
      <h4 className={styles.evalRubricHeading}>How this sheet score was derived</h4>
      <ul className={styles.evalDeriveList}>
        {summaryRows.map((row) => {
          const supplier = String(row.supplier ?? "");
          const contrib = rows
            .filter((r) => r.supplier === supplier)
            .reduce((acc, r) => acc + Number(r.contribution_pts ?? 0), 0);
          const sheetScore =
            envelope === "technical" ? row.technical_score : row.commercial_score;
          return (
            <li key={supplier}>
              <strong>{supplier}</strong>: rubric contributions sum to{" "}
              <strong>{contrib.toFixed(1)}</strong> pts → summary{" "}
              <strong>{String(sheetScore)}</strong> on this tab
              {Math.abs(contrib - Number(sheetScore)) > 0.25
                ? " (rounded for display)"
                : ""}
              .
            </li>
          );
        })}
      </ul>
    </>
  );
}
