import { useState } from "react";
import { type AuditRecord, type ChainReport, api } from "../api";
import { ErrorNote, Loading, shortHash, useLoad, when } from "../ui";

export default function AuditPage() {
  const first = useLoad(() => api.audit());
  const [older, setOlder] = useState<AuditRecord[]>([]);
  const [verify, setVerify] = useState<ChainReport | null>(null);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);

  if (first.error) return <ErrorNote message={first.error} />;
  if (!first.data) return <Loading what="the audit log" />;
  const items = [...first.data.items, ...older];
  const oldest = items.at(-1)?.seq ?? 1;

  const runVerify = async () => {
    setBusy(true);
    setFailure(null);
    try {
      setVerify(await api.verify());
      setOlder([]);
      first.reload();
    } catch (e) {
      setFailure((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const loadOlder = async () => {
    try {
      const page = await api.audit(oldest);
      setOlder((o) => [...o, ...page.items]);
    } catch (e) {
      setFailure((e as Error).message);
    }
  };

  return (
    <>
      <header style={{ display: "flex", flexWrap: "wrap", gap: 16, alignItems: "flex-end", justifyContent: "space-between" }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <span className="eyebrow">Operate · Audit</span>
          <h1>Audit log</h1>
          <span className="sub">
            One append-only hash chain per organization. Each record's hash covers the one before it, so any edit or
            deletion breaks the chain from that record on.
          </span>
        </div>
        <button className="btn dark" onClick={runVerify} disabled={busy}>
          {busy ? "Verifying…" : "Verify chain"}
        </button>
      </header>

      {failure && <ErrorNote message={failure} />}
      {verify && (
        <div className={`banner ${verify.intact ? "ok" : "bad"}`} role="status">
          {verify.intact ? (
            <span>
              <strong>Chain intact.</strong> Records 1–{verify.records} verified · head{" "}
              <span className="mono">{shortHash(verify.head_hash, 16)}</span> · the check itself is logged as #
              {verify.records + 1}
            </span>
          ) : (
            <span>
              <strong>Chain broken at record {verify.first_broken_seq}.</strong> {verify.reason}
            </span>
          )}
        </div>
      )}

      <section className="panel" aria-label="Records">
        <div className="scroll-x">
          <table className="grid">
            <thead>
              <tr>
                <th>#</th>
                <th>When</th>
                <th>Actor</th>
                <th>Action</th>
                <th>Subject</th>
                <th>Hash</th>
              </tr>
            </thead>
            <tbody>
              {items.map((r) => (
                <tr key={r.seq}>
                  <td className="mono">{r.seq}</td>
                  <td className="muted" style={{ whiteSpace: "nowrap" }}>
                    {when(r.occurred_at)}
                  </td>
                  <td>{r.actor.replace(/_/g, " ")}</td>
                  <td className="mono">{r.action}</td>
                  <td className="mono">{r.subject}</td>
                  <td className="mono muted" title={`prev ${r.prev_hash}`}>
                    {shortHash(r.record_hash)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {oldest > 1 && (
          <div className="panel-body" style={{ borderTop: "1px solid var(--line)" }}>
            <button className="btn" onClick={loadOlder}>
              Load older records
            </button>
          </div>
        )}
      </section>
    </>
  );
}
