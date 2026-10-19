import { Link, NavLink } from "react-router";
import { useSession } from "../app/session";
import { initials, teamLabel } from "../lib/ui";
import { useDigitalWorkers, useMyInstances } from "./useWorkspaceQueries";

export function WorkspaceRail() {
  const { me, signOut } = useSession();
  const workers = useDigitalWorkers();
  const jobs = useMyInstances();
  if (!me) return null;
  const dept = teamLabel(me.team).split(" · ")[0];

  return (
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
      <Link to="/workspace/new" className="btn dark ws-new-job">
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true">
          <path d="M8 3v10M3 8h10" />
        </svg>
        New job
      </Link>
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        <span className="eyebrow">Digital workers</span>
        {workers.isLoading && <span className="muted">Loading…</span>}
        {!workers.isLoading && !workers.data?.length && <span className="empty">None active yet</span>}
        {workers.data?.map((w) => (
          <div key={w.seat} className="ws-worker-card">
            <span className="ws-worker-avatar" aria-hidden="true">
              {initials(w.display_name)}
            </span>
            <div style={{ display: "flex", flexDirection: "column", minWidth: 0 }}>
              <span style={{ fontWeight: 500 }}>{w.display_name}</span>
              <span className="muted" style={{ fontSize: 12 }}>
                {w.state === "ACTIVE" ? "Active" : w.state} · v{w.version}
              </span>
            </div>
          </div>
        ))}
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        <span className="eyebrow">My jobs</span>
        {!jobs.data?.length && <span className="empty">No jobs yet</span>}
        {jobs.data?.slice(0, 8).map((j) => (
          <NavLink
            key={j.instance_id}
            to={`/workspace/jobs/${j.instance_id}`}
            className={({ isActive }) => (isActive ? "ws-job-link active" : "ws-job-link")}
          >
            <span style={{ fontWeight: 500 }}>{j.title}</span>
            <span className="muted" style={{ fontSize: 12 }}>
              {j.instance_id} · {j.state_label}
            </span>
          </NavLink>
        ))}
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
  );
}
