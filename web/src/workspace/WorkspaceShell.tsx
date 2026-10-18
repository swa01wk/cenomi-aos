import { Link } from "react-router";
import { initials, teamLabel } from "../lib/ui";
import { useSession } from "../app/session";

export default function WorkspaceShell() {
  const { me, signOut } = useSession();
  if (!me) return null;
  const dept = teamLabel(me.team).split(" · ")[0];

  return (
    <div className="shell">
      <nav className="ws-rail" aria-label="Workspace">
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <div className="logo">AOS</div>
          <div style={{ display: "flex", flexDirection: "column" }}>
            <span style={{ fontWeight: 600 }}>Workspace</span>
            <span className="muted" style={{ fontSize: 12 }}>
              {dept}
            </span>
          </div>
        </div>
        <button type="button" className="btn primary" disabled title="Available once a digital worker is active" style={{ height: 40, justifyContent: "center" }}>
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true">
            <path d="M8 3v10M3 8h10" />
          </svg>
          New job
        </button>
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          <span className="eyebrow">Digital workers</span>
          <span className="empty">None active yet</span>
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          <span className="eyebrow">My jobs</span>
          <span className="empty">No jobs yet</span>
        </div>
        <div className="foot">
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <span className={`avatar ${me.console ? "console" : ""}`}>{initials(me.name)}</span>
            <div style={{ display: "flex", flexDirection: "column", minWidth: 0 }}>
              <span style={{ fontWeight: 500 }}>{me.name}</span>
              <span className="muted" style={{ fontSize: 12 }}>
                {teamLabel(me.team)} · {me.roles.join(", ").replace(/_/g, " ")}
              </span>
            </div>
          </div>
          {me.console && <Link to="/console/packs">Open the Console</Link>}
          <button type="button" onClick={signOut}>
            Sign out
          </button>
        </div>
      </nav>
      <main>
        <header style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <h1>Hello, {me.name.split(" ")[0]}</h1>
          <span className="sub">This is where you'll start jobs with digital workers and act on what they need from you.</span>
        </header>
        <div className="panel">
          <div className="panel-body" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            <h2>Nothing to do yet</h2>
            <span className="sub">
              No digital worker is active in your area. Once a Seat is published and activated in the Console, it shows up
              on the left and <strong>New job</strong> lets you start the work it offers.
            </span>
            <div className="chips">
              <span className="pill">M1 · Seat activation</span>
              <span className="pill">M2 · Jobs and workflows</span>
              <span className="pill">M3 · Approvals in the Workspace</span>
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}
