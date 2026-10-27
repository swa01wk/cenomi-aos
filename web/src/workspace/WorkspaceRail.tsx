import { Link, NavLink } from "react-router";
import { useSession } from "../app/session";
import { initials, teamLabel } from "../lib/ui";
import { BriefcaseIcon, PlusIcon, QueueIcon, SeatMark } from "./icons";
import { useDigitalWorkers, useMyInstances } from "./useWorkspaceQueries";

const SEAT_STATE_WORD: Record<string, string> = {
  PAUSED: "Paused",
  RETIRED: "Retired",
};

export function WorkspaceRail() {
  const { me, signOut } = useSession();
  const workers = useDigitalWorkers();
  const jobs = useMyInstances();
  if (!me) return null;

  return (
    <nav className="ws-rail" aria-label="Workspace">
      {workers.isLoading && <span className="muted">Loading…</span>}
      {!workers.isLoading && !workers.data?.length && <span className="empty">No digital worker active yet</span>}
      {workers.data?.map((w) => (
        <div key={w.seat} className="ws-worker-card">
          <SeatMark online={w.state === "ACTIVE"} />
          <div style={{ display: "flex", flexDirection: "column", minWidth: 0 }}>
            <span style={{ fontWeight: 800 }}>{w.display_name}</span>
            <span style={{ fontSize: 12, color: "var(--ink-2)" }}>
              Digital worker · {w.state === "ACTIVE" ? "" : `${SEAT_STATE_WORD[w.state] ?? w.state} · `}v{w.version}
            </span>
          </div>
        </div>
      ))}

      <Link to="/workspace/new" className="ws-new-job">
        <PlusIcon />
        New job
      </Link>

      <div className="ws-nav">
        <NavLink to="/workspace" end className={({ isActive }) => (isActive ? "ws-nav-link active" : "ws-nav-link")}>
          <BriefcaseIcon />
          My jobs
        </NavLink>
        <NavLink to="/workspace/queue" className={({ isActive }) => (isActive ? "ws-nav-link active" : "ws-nav-link")}>
          <QueueIcon />
          Team queue
        </NavLink>
      </div>

      <div className="ws-rail-group">
        <span className="eyebrow">Recent jobs</span>
        {!jobs.data?.length && <span className="empty">No jobs yet</span>}
        {jobs.data?.slice(0, 8).map((j) => (
          <NavLink
            key={j.instance_id}
            to={`/workspace/jobs/${j.instance_id}`}
            className={({ isActive }) => (isActive ? "ws-job-link active" : "ws-job-link")}
          >
            <span className="title">{j.title}</span>
            <span className="state">
              {j.instance_id} · {j.state_label}
            </span>
          </NavLink>
        ))}
      </div>

      <div className="foot">
        <div className="ws-me">
          <span className="avatar">{initials(me.name)}</span>
          <div className="who">
            <span style={{ fontWeight: 700 }}>{me.name}</span>
            <span>
              {teamLabel(me.team)} · {me.roles.join(", ").replace(/_/g, " ")}
            </span>
          </div>
        </div>
        <div className="ws-rail-actions">
          {me.console && <Link to="/console/packs">Open the Console</Link>}
          <button type="button" onClick={signOut}>
            Sign out
          </button>
        </div>
      </div>
    </nav>
  );
}
