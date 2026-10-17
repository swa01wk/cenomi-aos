import { useState } from "react";
import { type ValidationReport, api } from "../api";
import { ErrorNote, Loading, StatusPill, shortHash, useLoad, when } from "../ui";

const COUNT_ORDER = ["Role", "Seat", "Skill", "WorkflowDefinition", "Policy", "Verifier", "ArtifactType", "Resource",
  "ToolProvider", "EvalSuite", "files"];

export function ReportView({ report }: { report: ValidationReport }) {
  const issues = [...report.errors, ...report.warnings];
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <div className={`banner ${report.ok ? "ok" : "bad"}`} role="status">
        <strong>{report.ok ? "Valid" : "Not valid"}</strong>
        <span>
          {report.pack} v{report.version} · {report.errors.length} errors, {report.warnings.length} warnings · digest{" "}
          <span className="mono">{shortHash(report.digest, 12)}</span>
        </span>
      </div>
      <div className="chips">
        {COUNT_ORDER.filter((k) => k in report.counts).map((k) => [k, report.counts[k]] as const).map(([k, v]) => (
          <span key={k} className="pill">
            {k} {v}
          </span>
        ))}
      </div>
      {issues.length > 0 && (
        <div className="scroll-x">
          <table className="grid">
            <thead>
              <tr>
                <th>Severity</th>
                <th>Code</th>
                <th>Where</th>
                <th>Problem</th>
              </tr>
            </thead>
            <tbody>
              {issues.map((i, n) => (
                <tr key={n}>
                  <td>
                    <span className={`pill ${i.severity === "error" ? "bad" : "warn"}`}>{i.severity}</span>
                  </td>
                  <td className="mono">{i.code}</td>
                  <td className="mono">
                    {i.file}
                    {i.path && `:${i.path}`}
                  </td>
                  <td>{i.message}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

export default function PacksPage({ canSync }: { canSync: boolean }) {
  const { data, error, reload } = useLoad(api.packs);
  const [busy, setBusy] = useState<string | null>(null);
  const [result, setResult] = useState<{ name: string; report: ValidationReport; note?: string } | null>(null);
  const [failure, setFailure] = useState<string | null>(null);

  const act = async (name: string, kind: "validate" | "sync") => {
    setBusy(`${kind}:${name}`);
    setFailure(null);
    try {
      if (kind === "validate") {
        setResult({ name, report: await api.validate(name) });
      } else {
        const r = await api.sync(name);
        setResult({
          name,
          report: r.report,
          note: r.created ? `Stored as ${r.pack} v${r.version} (${r.status}).` : `Already stored: ${r.pack} v${r.version}, same digest.`,
        });
        reload();
      }
    } catch (e) {
      setFailure((e as Error).message);
    } finally {
      setBusy(null);
    }
  };

  if (error) return <ErrorNote message={error} />;
  if (!data) return <Loading what="packs" />;
  const stored = new Map(data.packs.map((p) => [p.name, p]));

  return (
    <>
      <header style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        <span className="eyebrow">Define · Domain packs</span>
        <h1>Domain packs</h1>
        <span className="sub">
          A pack is the YAML that defines a digital worker: its Seat, Skills, verifiers, connectors, policies and
          workflow. Sync stores a version; publishing (with Risk and owner approval) arrives in M1.
        </span>
      </header>

      {failure && <ErrorNote message={failure} />}

      <section aria-label="Packs" style={{ display: "flex", flexDirection: "column", gap: 16 }}>
        {data.available.map((name) => {
          const p = stored.get(name);
          return (
            <div key={name} className="panel">
              <div className="panel-head">
                <div style={{ display: "flex", flexDirection: "column" }}>
                  <h2 className="mono" style={{ fontSize: 15 }}>
                    {name}
                  </h2>
                  <span className="muted">
                    packs/{name} {p && `· owner ${p.owner.replace(/_/g, " ")}`}
                  </span>
                </div>
                <div style={{ display: "flex", gap: 8 }}>
                  <button className="btn" onClick={() => act(name, "validate")} disabled={busy !== null}>
                    {busy === `validate:${name}` ? "Validating…" : "Validate"}
                  </button>
                  <button
                    className="btn primary"
                    onClick={() => act(name, "sync")}
                    disabled={busy !== null || !canSync}
                    title={canSync ? "Validate and store this pack as a version" : "Needs platform admin, process owner or Seat owner"}
                  >
                    {busy === `sync:${name}` ? "Syncing…" : "Sync from folder"}
                  </button>
                </div>
              </div>
              {result?.name === name && (
                <div className="panel-body" style={{ borderBottom: "1px solid var(--line)" }}>
                  {result.note && <p style={{ marginTop: 0 }}>{result.note}</p>}
                  <ReportView report={result.report} />
                </div>
              )}
              {p && p.versions.length > 0 ? (
                <div className="scroll-x">
                  <table className="grid">
                    <thead>
                      <tr>
                        <th>Version</th>
                        <th>Status</th>
                        <th>Digest</th>
                        <th>Checks</th>
                        <th>Source</th>
                        <th>Stored by</th>
                        <th>When</th>
                      </tr>
                    </thead>
                    <tbody>
                      {p.versions.map((v) => (
                        <tr key={v.id}>
                          <td>
                            <a href={`#/console/versions/${v.id}`}>
                              v{v.version}
                            </a>
                          </td>
                          <td>
                            <StatusPill status={v.status} />
                          </td>
                          <td className="mono">{shortHash(v.digest)}</td>
                          <td>
                            {v.errors} errors · {v.warnings} warnings
                          </td>
                          <td>{v.source}</td>
                          <td>{v.created_by.replace(/_/g, " ")}</td>
                          <td className="muted">{when(v.created_at)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <div className="panel-body muted">Not stored yet. Sync it to create version 1.</div>
              )}
            </div>
          );
        })}
      </section>
    </>
  );
}
