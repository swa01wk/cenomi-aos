import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { client } from "../../api/client";
import { Skeleton, StatusPill, Tabs } from "../../components";
import { when } from "../../lib/ui";
import { workspaceKeys } from "../useWorkspaceQueries";
import type { InstanceSnapshot } from "./jobStreamReducer";
import { artifactViewComponent } from "./views";
import styles from "./job.module.css";

export function WorkPanel({
  snapshot,
  panelArtifactId,
  onSelectArtifact,
}: {
  snapshot: InstanceSnapshot;
  panelArtifactId: string | null;
  onSelectArtifact: (artifactId: string) => void;
}) {
  const artifacts = snapshot.artifacts;
  const activeId = panelArtifactId ?? artifacts[0]?.artifact_id ?? "";
  const summary = artifacts.find((a) => a.artifact_id === activeId);

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
    enabled: Boolean(activeId && version),
    queryFn: async () => {
      const { data, error } = await client.GET("/artifacts/{id}/versions/{version}", {
        params: { path: { id: activeId, version } },
      });
      if (error) throw error;
      return data!;
    },
  });

  if (!artifacts.length) {
    return (
      <aside aria-label="Work in progress" className={styles.workPanel}>
        <header className={styles.workHead}>
          <div>
            <div className="eyebrow">Work in progress</div>
            <div className={styles.workTitle}>Nothing yet</div>
          </div>
        </header>
        <div className={styles.workBody}>
          <p className={styles.workEmpty}>Documents fill in here as the digital worker saves them.</p>
        </div>
      </aside>
    );
  }

  const View = summary ? artifactViewComponent(summary.view.type) : null;
  const versions = detail.data?.versions ?? summary?.versions ?? [];
  const isLatest = summary ? version === summary.latest_version : true;

  const body = summary ? (
    <div className={styles.workBody}>
      {content.isLoading && <Skeleton />}
      {View && content.data && <View view={summary.view} version={content.data} />}
    </div>
  ) : null;

  return (
    <aside aria-label="Work in progress" className={styles.workPanel}>
      <header className={styles.workHead}>
        <div style={{ minWidth: 0 }}>
          <div className="eyebrow">Work in progress</div>
          <div className={styles.workTitle}>{summary?.name ?? "Documents"}</div>
        </div>
        {summary && (
          <div className={styles.workBadges}>
            <StatusPill state={summary.status} />
            <span className={styles.versionBadge}>
              Version {version}
              {isLatest ? " · saved" : " · earlier"}
            </span>
            {versions.length > 0 && (
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
      <Tabs
        label="Documents"
        activeId={activeId}
        onChange={(id) => {
          onSelectArtifact(id);
          const a = artifacts.find((x) => x.artifact_id === id);
          if (a) setViewVersion(a.latest_version);
        }}
        tabs={artifacts.map((a) => ({
          id: a.artifact_id,
          label: `${a.name} v${a.latest_version}`,
          panel: a.artifact_id === activeId ? body : null,
        }))}
      />
      {content.data && (
        <footer className={styles.workFoot}>
          v{version}
          {content.data.produced_by?.name ? ` · by ${content.data.produced_by.name}` : ""}
          {versions.find((v) => v.version === version)?.at
            ? ` · ${when(versions.find((v) => v.version === version)!.at)}`
            : ""}
        </footer>
      )}
    </aside>
  );
}
