import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useState } from "react";
import { client } from "../../api/client";
import { Skeleton, StatusPill, Tabs } from "../../components";
import { when } from "../../lib/ui";
import { workspaceKeys } from "../useWorkspaceQueries";
import type { InstanceSnapshot } from "./jobStreamReducer";
import { artifactViewComponent } from "./views";
import { SupplierQuotesView } from "./views/SupplierQuotesView";
import { SUPPLIER_QUOTES_TAB_ID } from "./workPanelConstants";
import { messageComposerArtifacts } from "./workComposerHint";
import { WorkPanelComposerHint } from "./WorkPanelComposerHint";
import { WorkPanelRfqDock } from "./WorkPanelRfqDock";
import { isJobClosed } from "./jobLifecycle";
import { showSendRfqsBar } from "./workSendRfqs";
import { showResendRfqsBar } from "./workResendRfqs";
import { showSharedAttachmentsBar } from "./workSharedAttachments";
import { stageGuideIsLive, workPanelStageGuide } from "./stageGuideLogic";
import { WorkPanelStageGuide } from "./WorkPanelStageGuide";
import styles from "./job.module.css";

function resolvePanelArtifactId(
  panelArtifactId: string | null,
  artifacts: InstanceSnapshot["artifacts"],
  quoteTabAvailable: boolean,
): string {
  if (panelArtifactId === SUPPLIER_QUOTES_TAB_ID && quoteTabAvailable) {
    return SUPPLIER_QUOTES_TAB_ID;
  }
  if (
    panelArtifactId &&
    panelArtifactId !== "work" &&
    artifacts.some((a) => a.artifact_id === panelArtifactId)
  ) {
    return panelArtifactId;
  }
  return artifacts[0]?.artifact_id ?? "";
}

export function WorkPanel({
  instanceId,
  snapshot,
  panelArtifactId,
  onSelectArtifact,
  onSendRfqs,
  onResendRfqs,
  onUploadSharedAttachment,
  onRemoveSharedAttachment,
  onSaveArtifactVersion,
  agentBusy = false,
  onClose,
}: {
  instanceId: string;
  snapshot: InstanceSnapshot;
  panelArtifactId: string | null;
  onSelectArtifact: (artifactId: string) => void;
  onSendRfqs?: () => Promise<void>;
  onResendRfqs?: (supplierIds?: string[]) => Promise<void>;
  onUploadSharedAttachment?: (file: File) => Promise<void>;
  onRemoveSharedAttachment?: (attachmentId: string) => Promise<void>;
  onSaveArtifactVersion?: (
    artifactId: string,
    baseVersion: number,
    content: Record<string, unknown>,
  ) => Promise<void>;
  agentBusy?: boolean;
  onClose?: () => void;
}) {
  const queryClient = useQueryClient();
  const artifacts = snapshot.artifacts;
  const quoteArtifacts = artifacts.filter((a) => a.artifact_type === "quote" && a.latest_version >= 1);
  const showSupplierQuotesTab =
    quoteArtifacts.length >= 1 &&
    (snapshot.state === "awaiting_quotes" ||
      snapshot.state === "comparison" ||
      snapshot.state === "awaiting_proposals" ||
      snapshot.state === "closed");
  const activeId = resolvePanelArtifactId(panelArtifactId, artifacts, showSupplierQuotesTab);
  const summary =
    activeId === SUPPLIER_QUOTES_TAB_ID ? undefined : artifacts.find((a) => a.artifact_id === activeId);

  const artifactPrefetchKey = useMemo(
    () => artifacts.map((a) => `${a.artifact_id}:${a.latest_version}`).join("|"),
    [artifacts],
  );

  useEffect(() => {
    for (const a of artifacts) {
      const version = a.latest_version;
      void queryClient.prefetchQuery({
        queryKey: workspaceKeys.artifact(a.artifact_id),
        queryFn: async () => {
          const { data, error } = await client.GET("/artifacts/{id}", {
            params: { path: { id: a.artifact_id } },
          });
          if (error) throw error;
          return data!;
        },
        staleTime: 15_000,
      });
      void queryClient.prefetchQuery({
        queryKey: workspaceKeys.artifactVersion(a.artifact_id, version),
        queryFn: async () => {
          const { data, error } = await client.GET("/artifacts/{id}/versions/{version}", {
            params: { path: { id: a.artifact_id, version } },
          });
          if (error) throw error;
          return data!;
        },
        staleTime: 5_000,
      });
    }
  }, [artifactPrefetchKey, queryClient]);

  const [viewVersion, setViewVersion] = useState<number | null>(null);

  useEffect(() => {
    if (summary) setViewVersion(summary.latest_version);
  }, [summary?.artifact_id, summary?.latest_version]);

  const version = viewVersion ?? summary?.latest_version ?? 1;

  const detail = useQuery({
    queryKey: workspaceKeys.artifact(activeId),
    enabled: Boolean(activeId),
    queryFn: async () => {
      const { data, error } = await client.GET("/artifacts/{id}", {
        params: { path: { id: activeId } },
      });
      if (error) throw error;
      return data!;
    },
  });

  const content = useQuery({
    queryKey: workspaceKeys.artifactVersion(activeId, version),
    enabled: Boolean(activeId && activeId !== SUPPLIER_QUOTES_TAB_ID && version),
    queryFn: async () => {
      const { data, error } = await client.GET("/artifacts/{id}/versions/{version}", {
        params: { path: { id: activeId, version } },
      });
      if (error) throw error;
      return data!;
    },
  });

  const onSave = useCallback(
    async (nextContent: Record<string, unknown>) => {
      if (!onSaveArtifactVersion || !summary) return;
      await onSaveArtifactVersion(summary.artifact_id, version, nextContent);
      setViewVersion(null);
    },
    [onSaveArtifactVersion, summary, version],
  );

  const composerDrafts = messageComposerArtifacts(artifacts);
  const highlightComposerTabs = composerDrafts.length > 0;
  const composerTabIds = new Set(composerDrafts.map((a) => a.artifact_id));
  const viewingComposerDraft = Boolean(summary && composerTabIds.has(summary.artifact_id));
  const rfqFocusMode =
    highlightComposerTabs && viewingComposerDraft && snapshot.state !== "awaiting_quotes";
  const previewExpand =
    snapshot.state === "awaiting_quotes" ||
    snapshot.state === "rfq_sending" ||
    snapshot.state === "rfq_drafting" ||
    snapshot.state === "shortlisting";

  const tabArtifacts =
    rfqFocusMode && composerDrafts.length
      ? [...composerDrafts, ...artifacts.filter((a) => !composerTabIds.has(a.artifact_id))]
      : artifacts;

  const documentTabs = showSupplierQuotesTab
    ? [
        {
          artifact_id: SUPPLIER_QUOTES_TAB_ID,
          name: `Supplier quotes (${Math.max(quoteArtifacts.length, 1)})`,
          latest_version: 1,
        } as InstanceSnapshot["artifacts"][number],
        ...tabArtifacts,
      ]
    : tabArtifacts;

  if (!artifacts.length) {
    const emptyDetail =
      snapshot.state === "conversation"
        ? "Keep chatting with your details. When intake starts, the brief draft lands here."
        : snapshot.state === "intake"
          ? "The specialist is building your brief — it will show up here in a moment."
          : "Documents fill in here as the digital worker saves them.";
    const panelGuide = workPanelStageGuide(snapshot, agentBusy);
    const panelGuideLive = panelGuide ? stageGuideIsLive(panelGuide, snapshot.state) : false;
    return (
      <aside
        aria-label="Work in progress"
        className={[styles.workPanel, agentBusy ? styles.workPanelComposerGlow : ""].filter(Boolean).join(" ")}
      >
        <header className={styles.workHead}>
          <div style={{ minWidth: 0 }}>
            <div className="eyebrow">Work in progress</div>
            <div className={styles.workTitle}>
              {snapshot.state === "intake"
                ? "Brief drafting"
                : snapshot.state === "conversation" &&
                    snapshot.turns.some((t) => t.author.kind === "person") &&
                    snapshot.turns.some((t) => t.author.kind === "seat")
                  ? "Starting intake"
                  : "Nothing yet"}
            </div>
          </div>
          {onClose ? (
            <button type="button" className="btn" onClick={onClose}>
              Close
            </button>
          ) : null}
        </header>
        <div className={styles.workBody}>
          {agentBusy ? (
            <p className={styles.workLivePreview} role="status">
              Live preview — drafts update here as the worker saves them.
            </p>
          ) : null}
          {panelGuide ? (
            <WorkPanelStageGuide guide={panelGuide} live={panelGuideLive} workflowState={snapshot.state} />
          ) : null}
          {agentBusy ? <Skeleton /> : null}
          <p className={styles.workEmpty}>{emptyDetail}</p>
        </div>
      </aside>
    );
  }

  const View = summary ? artifactViewComponent(summary.view.type) : null;
  const versions = detail.data?.versions ?? summary?.versions ?? [];
  const isLatest = summary ? version === summary.latest_version : true;
  const rfqDraftEditable =
    snapshot.state === "rfq_drafting" || snapshot.state === "rfq_sending";
  const cdoMasterRfpReview = snapshot.pending.some(
    (p) => p.status === "open" && p.event === "decision.master_rfp_confirmed",
  );
  const masterRfpCdoEdit =
    snapshot.state === "master_rfp_drafting" &&
    snapshot.my_roles.includes("procurement_approver") &&
    summary?.artifact_type === "master_rfp" &&
    summary?.status === "draft" &&
    isLatest &&
    cdoMasterRfpReview;
  const rfqEdit =
    snapshot.my_roles.includes("buyer") &&
    isLatest &&
    rfqDraftEditable &&
    summary?.status === "draft" &&
    summary.view.type === "message_composer";
  const canEditDraft = rfqEdit || masterRfpCdoEdit;

  const body =
    activeId === SUPPLIER_QUOTES_TAB_ID ? (
      <div key={activeId} className={styles.workDraftScroll}>
        <SupplierQuotesView snapshot={snapshot} />
      </div>
    ) : summary ? (
      <div key={activeId} className={styles.workDraftScroll}>
        {content.isLoading && <Skeleton />}
        {View && content.data ? (
          <View
            view={summary.view}
            version={content.data}
            artifactId={summary.artifact_id}
            artifactStatus={summary.status}
            latestVersion={summary.latest_version}
            canEdit={canEditDraft}
            onSave={canEditDraft ? onSave : undefined}
          />
        ) : null}
      </div>
    ) : null;

  const panelGuide = workPanelStageGuide(snapshot, agentBusy);
  const panelGuideLive = panelGuide ? stageGuideIsLive(panelGuide, snapshot.state) : false;
  const closed = isJobClosed(snapshot);

  const showDock =
    (onSendRfqs && showSendRfqsBar(snapshot)) ||
    (onResendRfqs && showResendRfqsBar(snapshot)) ||
    (onUploadSharedAttachment && onRemoveSharedAttachment && showSharedAttachmentsBar(snapshot));

  return (
    <aside
      aria-label={closed ? "Completed job documents" : "Work in progress"}
      className={[
        styles.workPanel,
        closed ? styles.workPanel_closed : "",
        highlightComposerTabs ? styles.workPanelComposerGlow : "",
        rfqFocusMode ? styles.workPanelRfqFocus : "",
        previewExpand ? styles.workPanelPreviewExpand : "",
      ]
        .filter(Boolean)
        .join(" ")}
    >
      <div className={styles.workPanelScroll}>
      <header className={[styles.workHead, rfqFocusMode ? styles.workHeadCompact : ""].filter(Boolean).join(" ")}>
        <div style={{ minWidth: 0 }}>
          {!rfqFocusMode ? <div className="eyebrow">{closed ? "Completed job" : "Work in progress"}</div> : null}
          <div className={styles.workTitle}>
            {activeId === SUPPLIER_QUOTES_TAB_ID ? "Supplier quotes" : (summary?.name ?? "Documents")}
          </div>
        </div>
        {onClose ? (
          <button type="button" className="btn" onClick={onClose}>
            Close
          </button>
        ) : null}
        {summary && (
          <div className={styles.workBadges}>
            <StatusPill state={summary.status} />
            <span className={styles.versionBadge}>
              v{version}
              {isLatest ? " · latest" : " · earlier"}
            </span>
            {versions.length > 1 && (
              <select
                aria-label="Version"
                className={styles.versionSelect}
                value={version}
                onChange={(e) => setViewVersion(Number(e.target.value))}
              >
                {versions.map((v) => (
                  <option key={v.version} value={v.version}>
                    v{v.version} · {when(v.at)}
                  </option>
                ))}
              </select>
            )}
          </div>
        )}
      </header>

      {!rfqFocusMode ? (
        <>
          <WorkPanelComposerHint
            instanceId={instanceId}
            snapshot={snapshot}
            activeArtifactId={activeId}
            onOpenDraft={onSelectArtifact}
          />
          {agentBusy ? (
            <p className={styles.workLivePreview} role="status">
              Live preview — drafts update here as the worker saves them.
            </p>
          ) : null}
          {panelGuide ? (
            <WorkPanelStageGuide guide={panelGuide} live={panelGuideLive} workflowState={snapshot.state} />
          ) : null}
        </>
      ) : null}

      <div className={[styles.workMain, styles.workTabsWrap].join(" ")}>
        <Tabs
          label="Documents"
          activeId={activeId}
          onChange={(id) => {
            onSelectArtifact(id);
            const a = artifacts.find((x) => x.artifact_id === id);
            if (a) setViewVersion(a.latest_version);
          }}
          tabs={documentTabs.map((a) => ({
            id: a.artifact_id,
            label:
              a.artifact_id === SUPPLIER_QUOTES_TAB_ID
                ? a.name
                : composerTabIds.has(a.artifact_id)
                  ? a.name
                  : `${a.name} v${a.latest_version}`,
            tabClassName: composerTabIds.has(a.artifact_id) ? styles.workComposerTab : undefined,
            panel: a.artifact_id === activeId ? body : null,
          }))}
        />
      </div>

      {content.data && !rfqFocusMode ? (
        <footer className={styles.workFoot}>
          v{version}
          {content.data.produced_by?.name ? ` · by ${content.data.produced_by.name}` : ""}
          {versions.find((v) => v.version === version)?.at
            ? ` · ${when(versions.find((v) => v.version === version)!.at)}`
            : ""}
        </footer>
      ) : null}
      </div>

      {showDock ? (
        <WorkPanelRfqDock
          snapshot={snapshot}
          onSend={onSendRfqs}
          onResend={onResendRfqs}
          onUpload={onUploadSharedAttachment}
          onRemove={onRemoveSharedAttachment}
        />
      ) : null}
    </aside>
  );
}
