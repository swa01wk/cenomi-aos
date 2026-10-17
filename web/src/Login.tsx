import { useState } from "react";
import { type Person, type Session, api } from "./api";
import { ErrorNote, Loading, initials, teamLabel, useLoad } from "./ui";

export default function Login({ onSignedIn }: { onSignedIn: (s: Session) => void }) {
  const { data: people, error } = useLoad(api.personas);
  const [busy, setBusy] = useState<string | null>(null);
  const [failure, setFailure] = useState<string | null>(null);

  const pick = async (p: Person) => {
    setBusy(p.id);
    setFailure(null);
    try {
      onSignedIn(await api.signIn(p.id));
    } catch (e) {
      setFailure((e as Error).message);
      setBusy(null);
    }
  };

  const group = (console: boolean) => (people ?? []).filter((p) => p.console === console);

  return (
    <div className="login">
      <div className="login-card">
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <div className="logo">AOS</div>
          <div style={{ display: "flex", flexDirection: "column" }}>
            <h1>Sign in</h1>
            <span className="sub">POC sandbox organization</span>
          </div>
        </div>
        <div className="banner info">
          POC sign-in: pick a seeded person. Each one sees what their roles allow; single sign-on replaces this after
          the POC.
        </div>
        {error && <ErrorNote message={`Can't reach the kernel: ${error}`} />}
        {failure && <ErrorNote message={failure} />}
        {!people && !error && <Loading what="people" />}
        {people && (
          <>
            <Section title="Workspace" hint="Request, buy and approve work" people={group(false)} busy={busy} onPick={pick} />
            <Section title="Console" hint="Define, govern and operate digital workers" people={group(true)} busy={busy} onPick={pick} />
          </>
        )}
      </div>
    </div>
  );
}

function Section(props: { title: string; hint: string; people: Person[]; busy: string | null; onPick: (p: Person) => void }) {
  return (
    <section aria-label={props.title} style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      <div>
        <h2>{props.title}</h2>
        <span className="muted">{props.hint}</span>
      </div>
      <div className="persona-grid">
        {props.people.map((p) => (
          <button key={p.id} className="persona" onClick={() => props.onPick(p)} disabled={props.busy !== null}>
            <span className={`avatar ${p.console ? "console" : ""}`}>{initials(p.name)}</span>
            <span className="who">
              <span style={{ fontWeight: 500 }}>{props.busy === p.id ? "Signing in…" : p.name}</span>
              <span className="muted" style={{ fontSize: 12 }}>
                {teamLabel(p.team)} · {p.roles.join(", ").replace(/_/g, " ")}
              </span>
            </span>
          </button>
        ))}
      </div>
    </section>
  );
}
