import { useQueries, useQuery } from "@tanstack/react-query";
import { client } from "../../../api/client";
import { Skeleton } from "../../../components";
import { workspaceKeys } from "../../useWorkspaceQueries";
import type { InstanceSnapshot } from "../jobStreamReducer";
import { supplierShortName } from "../supplierDisplayNames";
import { DocumentPdfDownload } from "./DocumentPdfDownload";
import { FieldListView } from "./FieldListView";
import { ClarificationNotesEditor } from "./ClarificationNotesEditor";
import { proposalReplyHeading, type ProposalReplyContent } from "./proposalReplyLabels";
import styles from "./views.module.css";

type Props = {
  snapshot: InstanceSnapshot;
  onSaveArtifactVersion?: (
    artifactId: string,
    baseVersion: number,
    content: Record<string, unknown>,
  ) => Promise<void>;
};

type ProposalContent = ProposalReplyContent & { total?: number };

function useProposalVersionHistory(artifactId: string, latestVersion: number) {
  return useQueries({
    queries: Array.from({ length: Math.max(0, latestVersion) }, (_, i) => {
      const ver = i + 1;
      return {
        queryKey: workspaceKeys.artifactVersion(artifactId, ver),
        queryFn: async () => {
          const { data, error } = await client.GET("/artifacts/{id}/versions/{version}", {
            params: { path: { id: artifactId, version: ver } },
          });
          if (error) throw error;
          return data!;
        },
        staleTime: 30_000,
      };
    }),
  });
}

function clarificationEditable(
  snapshot: InstanceSnapshot,
  content: ProposalReplyContent,
  ver: number,
  latestVersion: number,
): boolean {
  if (content.reply_kind !== "question" || ver !== latestVersion) return false;
  const lane = content.question_lane;
  if (lane === "commercial" && snapshot.my_roles.includes("buyer")) return true;
  if (lane === "technical" && snapshot.my_roles.includes("category_manager")) return true;
  return false;
}

function SupplierProposalStack({
  meta,
  snapshot,
  onSaveArtifactVersion,
}: {
  meta: InstanceSnapshot["artifacts"][number];
  snapshot: InstanceSnapshot;
  onSaveArtifactVersion?: Props["onSaveArtifactVersion"];
}) {
  const versions = useProposalVersionHistory(meta.artifact_id, meta.latest_version);
  const latest = versions[meta.latest_version - 1]?.data?.content as ProposalContent | undefined;
  const label = meta.key ? supplierLabel(meta.key, latest) : meta.name;

  return (
    <section key={meta.artifact_id} aria-label={label} className={styles.quoteStackSection}>
      <h3 className={styles.quoteStackHeading}>{label}</h3>
      {latest ? (
        <p className={styles.hiddenNote}>
          <strong>{statusLabel(latest.reply_kind, latest.acknowledged, latest.question_lane)}</strong>
          {meta.latest_version > 1
            ? ` · ${meta.latest_version} inbound messages (ack, clarifications, proposal)`
            : ""}
        </p>
      ) : null}
      <ProposalReplyTimeline
        meta={meta}
        versions={versions}
        snapshot={snapshot}
        onSaveArtifactVersion={onSaveArtifactVersion}
      />
    </section>
  );
}

function ProposalReplyTimeline({
  meta,
  versions,
  snapshot,
  onSaveArtifactVersion,
}: {
  meta: InstanceSnapshot["artifacts"][number];
  versions: ReturnType<typeof useProposalVersionHistory>;
  snapshot: InstanceSnapshot;
  onSaveArtifactVersion?: Props["onSaveArtifactVersion"];
}) {
  const anyLoading = versions.some((q) => q.isLoading);
  if (anyLoading) return <Skeleton />;

  return (
    <div className={styles.replyTimeline}>
      {versions.map((q, i) => {
        if (!q.data) return null;
        const content = (q.data.content ?? {}) as ProposalContent;
        const ver = i + 1;
        const heading = proposalReplyHeading(content, ver);
        return (
          <article key={ver} className={styles.replyTimelineItem} aria-label={heading}>
            <h4 className={styles.replyTimelineHeading}>{heading}</h4>
            {content.received_at ? (
              <p className={styles.hiddenNote}>Received {content.received_at}</p>
            ) : null}
            {content.reply_excerpt ? (
              <blockquote className={styles.replyExcerpt}>{content.reply_excerpt}</blockquote>
            ) : null}
            {content.reply_kind === "question" ? (
              <ClarificationNotesEditor
                content={content}
                artifactId={meta.artifact_id}
                version={ver}
                baseContent={(q.data?.content ?? {}) as Record<string, unknown>}
                canEdit={clarificationEditable(snapshot, content, ver, meta.latest_version)}
                onSave={onSaveArtifactVersion}
              />
            ) : null}
            {content.reply_kind === "proposal" ? (
              <FieldListView view={meta.view} version={q.data} />
            ) : null}
          </article>
        );
      })}
    </div>
  );
}

function supplierLabel(sid: string, content?: ProposalContent): string {
  const short = supplierShortName(sid);
  if (short) return short;
  return content?.supplier?.trim() || sid;
}

function statusLabel(
  kind: string | undefined,
  acknowledged: boolean | undefined,
  questionLane?: string,
): string {
  if (kind === "ack" || acknowledged) return "Acknowledged";
  if (kind === "question") {
    if (questionLane === "commercial") return "Clarification — procurement review";
    if (questionLane === "technical") return "Clarification — category manager review";
    return "Clarification pending review";
  }
  if (kind === "proposal") return "Full proposal received";
  return "Reply received";
}

export function SupplierQuotesView({ snapshot, onSaveArtifactVersion }: Props) {
  const masterRfp = snapshot.artifacts.find(
    (a) => a.artifact_type === "master_rfp" && a.latest_version >= 1,
  );
  const quotes = snapshot.artifacts.filter(
    (a) => a.artifact_type === "quote" && a.latest_version >= 1,
  );
  const proposals = snapshot.artifacts.filter(
    (a) => a.artifact_type === "proposal" && a.latest_version >= 1,
  );
  const rfqSuppliers = snapshot.artifacts
    .filter((a): a is (typeof snapshot.artifacts)[number] & { key: string } =>
      a.artifact_type === "rfq_email" && Boolean(a.key),
    )
    .map((a) => a.key);
  const rfpSuppliers = snapshot.artifacts
    .filter((a): a is (typeof snapshot.artifacts)[number] & { key: string } =>
      a.artifact_type === "rfp_invitation" && Boolean(a.key),
    )
    .map((a) => a.key);
  const invited = rfpSuppliers.length ? rfpSuppliers : rfqSuppliers;
  const attrs = (snapshot as InstanceSnapshot & { attributes?: Record<string, unknown> }).attributes;
  const invitedCount = typeof attrs?.invited_count === "number" ? attrs.invited_count : invited.length;
  const ackCount = typeof attrs?.ack_count === "number" ? attrs.ack_count : undefined;
  const replyCount = typeof attrs?.proposal_count === "number" ? attrs.proposal_count : proposals.length;

  const masterRfpQuery = useQuery({
    queryKey: masterRfp
      ? workspaceKeys.artifactVersion(masterRfp.artifact_id, masterRfp.latest_version)
      : ["artifact-version", "none"],
    enabled: Boolean(masterRfp),
    queryFn: async () => {
      const { data, error } = await client.GET("/artifacts/{id}/versions/{version}", {
        params: { path: { id: masterRfp!.artifact_id, version: masterRfp!.latest_version } },
      });
      if (error) throw error;
      return data!;
    },
  });

  const proposalQueries = useQueries({
    queries: proposals.map((q) => ({
      queryKey: workspaceKeys.artifactVersion(q.artifact_id, q.latest_version),
      queryFn: async () => {
        const { data, error } = await client.GET("/artifacts/{id}/versions/{version}", {
          params: { path: { id: q.artifact_id, version: q.latest_version } },
        });
        if (error) throw error;
        return data!;
      },
    })),
  });

  const queries = useQueries({
    queries: quotes.map((q) => ({
      queryKey: workspaceKeys.artifactVersion(q.artifact_id, q.latest_version),
      queryFn: async () => {
        const { data, error } = await client.GET("/artifacts/{id}/versions/{version}", {
          params: { path: { id: q.artifact_id, version: q.latest_version } },
        });
        if (error) throw error;
        return data!;
      },
    })),
  });

  const quotedKeys = new Set(quotes.map((q) => q.key || q.name));
  const proposalByKey = new Map<string, { meta: (typeof proposals)[number]; content?: ProposalContent }>();
  proposals.forEach((meta, i) => {
    const key = meta.key || meta.name;
    proposalByKey.set(key, {
      meta,
      content: proposalQueries[i]?.data?.content as ProposalContent | undefined,
    });
  });

  if (!quotes.length && !proposals.length && !invited.length) {
    return <p className={styles.hiddenNote}>No supplier replies yet.</p>;
  }

  const masterContent = masterRfpQuery.data?.content as Record<string, unknown> | undefined;

  return (
    <div className={styles.viewBody}>
      {masterRfp && snapshot.workflow === "sourcing_rfp" ? (
        <section className={styles.quoteStackSection} aria-label="Master RFP">
          <h3 className={styles.quoteStackHeading}>Master RFP</h3>
          <p className={styles.hiddenNote}>
            Shareable scope sent to suppliers after CDO approval. Use the Master RFP tab under Documents for the full
            document view.
          </p>
          {masterContent ? (
            <DocumentPdfDownload
              view={masterRfp.view}
              content={masterContent}
              artifactType="master_rfp"
            />
          ) : null}
          {masterRfpQuery.isLoading ? <Skeleton /> : null}
          {masterContent ? <FieldListView view={masterRfp.view} version={masterRfpQuery.data!} /> : null}
        </section>
      ) : null}
      {proposals.length || invited.length ? (
        <section className={styles.quoteStackSection} aria-label="RFP responses">
          <h3 className={styles.quoteStackHeading}>RFP responses</h3>
          <p className={styles.hiddenNote}>
            {ackCount != null
              ? `${ackCount} of ${invitedCount || invited.length} acknowledged`
              : `${replyCount} of ${invitedCount || invited.length} replied`}
            {snapshot.workflow === "sourcing_rfp"
              ? " — first reply should confirm receipt (ack); full proposals follow before the deadline."
              : ""}
          </p>
          <table className={styles.responseTable}>
            <thead>
              <tr>
                <th scope="col">Supplier</th>
                <th scope="col">Status</th>
              </tr>
            </thead>
            <tbody>
              {invited.map((sid) => {
                const row = proposalByKey.get(sid);
                const content = row?.content;
                const kind = content?.reply_kind;
                return (
                  <tr key={sid}>
                    <td>{supplierLabel(sid, content)}</td>
                    <td>
                      {content
                        ? statusLabel(kind, content.acknowledged, content.question_lane)
                        : "Awaiting reply"}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </section>
      ) : null}
      {proposals.map((meta) => (
        <SupplierProposalStack
          key={meta.artifact_id}
          meta={meta}
          snapshot={snapshot}
          onSaveArtifactVersion={onSaveArtifactVersion}
        />
      ))}
      {quotes.map((meta, i) => {
        const detail = queries[i];
        const quoteContent = detail.data?.content as ProposalContent | undefined;
        const label = meta.key ? supplierLabel(meta.key, quoteContent) : meta.name;
        return (
          <section key={meta.artifact_id} aria-label={label} className={styles.quoteStackSection}>
            <h3 className={styles.quoteStackHeading}>{label}</h3>
            {detail.isLoading && <Skeleton />}
            {detail.data ? <FieldListView view={meta.view} version={detail.data} /> : null}
            {detail.isError ? (
              <p className={styles.hiddenNote}>Could not load this quote — try the individual tab.</p>
            ) : null}
          </section>
        );
      })}
      {invited
        .filter(
          (sid) =>
            !proposalByKey.has(sid) &&
            !quotedKeys.has(sid) &&
            !quotes.some((q) => q.key === sid),
        )
        .map((sid) => (
          <section key={`wait-${sid}`} className={styles.quoteStackSection} aria-label={`Supplier ${sid}`}>
            <h3 className={styles.quoteStackHeading}>Supplier {sid}</h3>
            <p className={styles.hiddenNote}>
              No reply captured yet — refresh after email is ingested, or check the vendor replied on the RFP thread.
            </p>
          </section>
        ))}
      {rfqSuppliers
        .filter((sid) => !quotedKeys.has(sid) && !quotes.some((q) => q.key === sid))
        .map((sid) => (
          <section key={sid} className={styles.quoteStackSection} aria-label={`Supplier ${sid}`}>
            <h3 className={styles.quoteStackHeading}>Supplier {sid}</h3>
            <p className={styles.hiddenNote}>
              Reply received or pending — open the RFQ email tab for this supplier, or reload after the worker
              captures the quote.
            </p>
          </section>
        ))}
    </div>
  );
}
