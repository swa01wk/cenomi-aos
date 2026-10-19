import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams } from "react-router";
import { client } from "../api/client";
import { ErrorBanner, Skeleton, StatusPill } from "../components";
import { shortHash, when } from "../lib/ui";
import { ReportView } from "./PacksPage";

const ORDER = [
  "Pack",
  "Role",
  "Seat",
  "Skill",
  "WorkflowDefinition",
  "Policy",
  "Verifier",
  "ArtifactType",
  "Resource",
  "ToolProvider",
  "EvalSuite",
];

export default function VersionPage() {
  const { id = "" } = useParams<{ id: string }>();
  const [open, setOpen] = useState<{ kind: string; name: string } | null>(null);

  const versionQuery = useQuery({
    queryKey: ["pack-version", id],
    queryFn: async () => {
      const { data } = await client.GET("/console/pack-versions/{version_id}", {
        params: { path: { version_id: id } },
      });
      return data!;
    },
    enabled: !!id,
  });

  const definitionQuery = useQuery({
    queryKey: ["definition", id, open?.kind, open?.name],
    queryFn: async () => {
      if (!open) return null;
      const { data } = await client.GET("/console/pack-versions/{version_id}/definitions/{kind}/{name}", {
        params: { path: { version_id: id, kind: open.kind, name: open.name } },
      });
      return data!;
    },
    enabled: !!open,
  });

  if (versionQuery.error) return <ErrorBanner title="We couldn't load this version" detail={(versionQuery.error as Error).message} />;
  if (versionQuery.isPending || !versionQuery.data) return <Skeleton />;
  const v = versionQuery.data;
  const kinds = [...new Set(v.definitions.map((d) => d.kind))].sort(
    (a, b) => ORDER.indexOf(a ?? "") - ORDER.indexOf(b ?? ""),
  );

  return (
    <>
      <header style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        <Link to="/console/packs">← Domain packs</Link>
        <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
          <h1 className="mono" style={{ fontSize: 22 }}>
            {v.pack} v{v.version}
          </h1>
          <StatusPill state={v.status} />
        </div>
        <span className="sub">
          Digest <span className="mono">{shortHash(v.digest, 16)}</span> · source {v.source} · stored by{" "}
          {(v.created_by ?? "").replace(/_/g, " ")} · {when(v.created_at ?? "")}
        </span>
      </header>

      <section className="panel" aria-label="Validation">
        <div className="panel-head">
          <h2>Validation</h2>
        </div>
        <div className="panel-body">
          <ReportView report={v.validation} />
        </div>
      </section>

      <section className="split" aria-label="Definitions">
        <div className="panel">
          <div className="panel-head">
            <h2>Definitions</h2>
            <span className="muted">{v.definitions.length} objects</span>
          </div>
          <div className="deflist">
            {kinds.map((k) => (
              <div key={k}>
                <div className="eyebrow" style={{ padding: "10px 12px 4px" }}>
                  {k}
                </div>
                {v.definitions
                  .filter((d) => d.kind === k)
                  .map((d) => (
                    <button
                      key={d.name}
                      type="button"
                      aria-pressed={open?.kind === d.kind && open?.name === d.name}
                      onClick={() => setOpen({ kind: d.kind ?? "", name: d.name ?? "" })}
                    >
                      <span className="mono">{d.name}</span>
                      <span className="muted mono">{d.file}</span>
                    </button>
                  ))}
              </div>
            ))}
          </div>
        </div>
        <div className="panel">
          <div className="panel-head">
            <h2>{open ? `${open.kind} · ${open.name}` : "Pick a definition"}</h2>
          </div>
          <div className="panel-body">
            {!open && <span className="muted">The stored spec is shown exactly as the kernel will pin it.</span>}
            {open && definitionQuery.error && (
              <ErrorBanner title="We couldn't load this definition" detail={(definitionQuery.error as Error).message} />
            )}
            {open && definitionQuery.data && <pre className="json">{JSON.stringify(definitionQuery.data, null, 2)}</pre>}
          </div>
        </div>
      </section>
    </>
  );
}
