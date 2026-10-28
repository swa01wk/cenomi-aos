import { useMemo } from "react";
import { Link, NavLink } from "react-router";
import { useSession } from "../app/session";
import { initials, teamLabel } from "../lib/ui";
import { BriefcaseIcon, PlusIcon, QueueIcon, SeatMark } from "./icons";
import {
  countJobsNeedingViewer,
  jobNeedsViewerAction,
  pendingActionLabel,
  sortJobsForViewer,
} from "./instanceAttention";
import { useDigitalWorkers, useMyInstances } from "./useWorkspaceQueries";

const SEAT_STATE_WORD: Record<string, string> = {
  PAUSED: "Paused",
  RETIRED: "Retired",
};

function RailJobLink({
  instanceId,
  title,
  meta,
  needsYou,
}: {
  instanceId: string;
  title: string;
  meta: string;
  needsYou?: boolean;
}) {
  return (
    <NavLink
      to={`/workspace/jobs/${instanceId}`}
      className={({ isActive }) =>
        ["ws-job-link", isActive ? "active" : "", needsYou ? "needs-you" : ""].filter(Boolean).join(" ")
      }
    >
      {needsYou && <span className="ws-job-needs-badge">Needs you</span>}
      <span className="title">{title}</span>
      <span className="state">{meta}</span>
    </NavLink>
  );
}

export function WorkspaceRail() {
  const { me, signOut } = useSession();
  const workers = useDigitalWorkers();
  const jobs = useMyInstances();
  const needsYouCount = countJobsNeedingViewer(jobs.data, me?.id ?? "");
  const railJobs = useMemo(() => {
    if (!jobs.data?.length || !me) return [];
    return sortJobsForViewer(jobs.data, me.id).slice(0, 8);
  }, [jobs.data, me]);
  const needsYouJobs = useMemo(
    () => railJobs.filter((j) => jobNeedsViewerAction(j, me?.id ?? "")),
    [railJobs, me?.id],
  );
  const recentJobs = useMemo(
    () => railJobs.filter((j) => !jobNeedsViewerAction(j, me?.id ?? "")),
    [railJobs, me?.id],
  );
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
          {needsYouCount > 0 && (
            <span className="ws-nav-badge" aria-label={`${needsYouCount} need your action`}>
              {needsYouCount}
            </span>
          )}
        </NavLink>
        <NavLink to="/workspace/queue" className={({ isActive }) => (isActive ? "ws-nav-link active" : "ws-nav-link")}>
          <QueueIcon />
          Team queue
        </NavLink>
      </div>

      {needsYouJobs.length > 0 && (
        <div className="ws-rail-group ws-rail-group-attention">
          <span className="eyebrow ws-eyebrow-attention">Needs your action</span>
          {needsYouJobs.map((j) => (
            <RailJobLink
              key={j.instance_id}
              instanceId={j.instance_id}
              title={j.title}
              meta={`${pendingActionLabel(j)} · ${j.instance_id}`}
              needsYou
            />
          ))}
        </div>
      )}

      <div className="ws-rail-group">
        <span className="eyebrow">{needsYouJobs.length > 0 ? "Other recent jobs" : "Recent jobs"}</span>
        {!jobs.data?.length && <span className="empty">No jobs yet</span>}
        {recentJobs.map((j) => (
          <RailJobLink
            key={j.instance_id}
            instanceId={j.instance_id}
            title={j.title}
            meta={`${j.instance_id} · ${j.state_label}`}
          />
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
