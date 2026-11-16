import { useQuery } from "@tanstack/react-query";
import { client } from "../../api/client";
import { SeatMark } from "../icons";
import { workspaceKeys } from "../useWorkspaceQueries";
import type { components } from "../../api/schema";
import { briefSummaryProse } from "./briefSummaryProse";
import styles from "./job.module.css";

type ArtifactView = components["schemas"]["ArtifactView"];

export function BriefSummaryMessage({
  artifactId,
  version,
  view,
  specialistName,
}: {
  artifactId: string;
  version: number;
  view: ArtifactView;
  specialistName: string;
}) {
  const { data, isLoading, isError } = useQuery({
    queryKey: workspaceKeys.artifactVersion(artifactId, version),
    queryFn: async () => {
      const { data: body, error } = await client.GET("/artifacts/{id}/versions/{version}", {
        params: { path: { id: artifactId, version } },
      });
      if (error) throw error;
      return body!;
    },
    staleTime: 30_000,
  });

  const prose = data?.content
    ? briefSummaryProse(data.content as Record<string, unknown>, view)
    : null;

  return (
    <article className={styles.agentBlock} aria-label={`Request summary from ${specialistName}`}>
      <header className={styles.briefSummaryHead}>
        <SeatMark small />
        <div>
          <span className={styles.briefSummaryName}>{specialistName}</span>
          <span className={styles.briefSummaryMeta}>From your brief draft</span>
        </div>
      </header>
      <div className={styles.briefSummaryBody}>
        {isLoading ? <p className="muted">Reading your brief…</p> : null}
        {isError ? (
          <p className="muted">Open Documents to review the brief draft.</p>
        ) : prose ? (
          <>
            <p className={styles.briefSummaryLead}>Here&apos;s what I captured for your request:</p>
            <p>{prose}</p>
          </>
        ) : null}
      </div>
    </article>
  );
}
