import { useState } from "react";
import { api } from "../api";
import { ErrorNote, Loading, StatusPill, shortHash, useLoad, when } from "../ui";
import { ReportView } from "./PacksPage";

const ORDER = ["Pack", "Role", "Seat", "Skill", "WorkflowDefinition", "Policy", "Verifier", "ArtifactType", "Resource", "ToolProvider", "EvalSuite"];

export default function VersionPage({ id }: { id: string }) {
  const { data: v, error } = useLoad(() => api.version(id), [id]);
  const [open, setOpen] = useState<{ kind: string; name: string } | null>(null);
  const spec = useLoad(
    () => (open ? api.definition(id, open.kind, open.name) : Promise.resolve(null)),
    [id, open?.kind, open?.name],
  );

  if (error) return <ErrorNote message={error} />;
  if (!v) return <Loading what="the pack version" />;
  const kinds = [...new Set(v.definitions.map((d) => d.kind))].sort((a, b) => ORDER.indexOf(a) - ORDER.indexOf(b));

  return (
    <>
      <header style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        <a href="#/console/packs">
          ← Domain packs
        </a>
        <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
          <h1 className="mono" style={{ fontSize: 22 }}>
            {v.pack} v{v.version}
          </h1>
          <StatusPill status={v.status} />
        </div>
        <span className="sub">
          Digest <span className="mono">{shortHash(v.digest, 16)}</span> · source {v.source} · stored by{" "}
          {v.created_by.replace(/_/g, " ")} · {when(v.created_at)}
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
                      aria-pressed={open?.kind === d.kind && open?.name === d.name}
                      onClick={() => setOpen({ kind: d.kind, name: d.name })}
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
            {open && spec.error && <ErrorNote message={spec.error} />}
            {open && spec.data && <pre className="json">{JSON.stringify(spec.data, null, 2)}</pre>}
          </div>
        </div>
      </section>
    </>
  );
}
