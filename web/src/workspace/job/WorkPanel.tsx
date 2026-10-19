import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { client } from "../../api/client";
import { Skeleton, StatusPill } from "../../components";
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
        <p className="muted" style={{ padding: 20 }}>
          Documents from the worker will appear here.
        </p>
      </aside>
    );
  }

  const View = summary ? artifactViewComponent(summary.view.type) : null;

  return (
    <aside aria-label="Work in progress" className={styles.workPanel}>
      <div role="tablist" aria-label="Artifacts" className={styles.workTabs}>
        {artifacts.map((a) => (
          <button
            key={a.artifact_id}
            type="button"
            role="tab"
            aria-selected={a.artifact_id === activeId}
            className={styles.workTab}
            onClick={() => {
              onSelectArtifact(a.artifact_id);
              setViewVersion(a.latest_version);
            }}
          >
            {a.name} v{a.latest_version}
          </button>
        ))}
      </div>
      {summary && (
        <div className={styles.workMeta}>
          <StatusPill state={summary.status} />
          <span className="muted" style={{ fontSize: 12 }}>
            v{version}
            {detail.data?.versions?.length ? (
              <>
                {" "}
                ·{" "}
                <select
                  aria-label="Version"
                  value={version}
                  onChange={(e) => setViewVersion(Number(e.target.value))}
                >
                  {(detail.data.versions ?? summary.versions ?? []).map((v) => (
                    <option key={v.version} value={v.version}>
                      v{v.version} · {v.by} · {new Date(v.at).toLocaleString()}
                    </option>
                  ))}
                </select>
              </>
            ) : null}
          </span>
        </div>
      )}
      {content.isLoading && <Skeleton />}
      {View && content.data && summary && (
        <View view={summary.view} version={content.data} />
      )}
    </aside>
  );
}
