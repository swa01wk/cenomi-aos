import { useMemo } from "react";
import { Link, NavLink } from "react-router";
import { useSession } from "../app/session";
import { initials, teamLabel } from "../lib/ui";
import { BriefcaseIcon, MessageIcon, PlusIcon, QueueIcon } from "./icons";
import {
  countJobsNeedingViewer,
  jobNeedsViewerAction,
  pendingActionLabel,
  sortJobsForViewer,
} from "./instanceAttention";
import { workerColleagueName, workerInitials } from "./persona";
import { entryColleague, isEntryColleague } from "./workspaceEntry";
import { personChatPath, jobDetailPath } from "./jobPaths";
import { useDigitalWorkers, useMyInstances, useQueue } from "./useWorkspaceQueries";

function RailJobLink({
  instanceId,
  seat,
  title,
  detail,
  needsYou,
  chatStyle,
}: {
  instanceId: string;
  seat?: string;
  title: string;
  detail: string;
  needsYou?: boolean;
  chatStyle?: boolean;
}) {
  const to =
    chatStyle && seat ? personChatPath(seat, instanceId) : jobDetailPath(instanceId);
  return (
    <NavLink
      to={to}
      className={({ isActive }) =>
        ["ws-job-link", isActive ? "active" : "", needsYou ? "needs-you" : ""].filter(Boolean).join(" ")
      }
    >
      {needsYou && <span className="ws-job-needs-badge">Needs you</span>}
      <span className="ws-job-id">{instanceId}</span>
      <span className="title">{title}</span>
      <span className="state">{detail}</span>
    </NavLink>
  );
}

export function WorkspaceRail() {
  const { me, signOut } = useSession();
  const workers = useDigitalWorkers();
  const jobs = useMyInstances();
  const queue = useQueue(me?.team);
  const queueCount = queue.data?.length ?? 0;
  const needsYouCount = countJobsNeedingViewer(jobs.data, me?.id ?? "");
  const activeWorkers = useMemo(
    () => workers.data?.filter((w) => w.state === "ACTIVE") ?? [],
    [workers.data],
  );
  const entry = useMemo(() => entryColleague(activeWorkers), [activeWorkers]);
  const directColleagues = useMemo(
    () => activeWorkers.filter((w) => !isEntryColleague(w)),
    [activeWorkers],
  );
  const railJobs = useMemo(() => {
    if (!jobs.data?.length || !me) return [];
    return sortJobsForViewer(jobs.data, me.id).slice(0, 6);
  }, [jobs.data, me]);
  const needsYouJobs = useMemo(
    () => railJobs.filter((j) => jobNeedsViewerAction(j, me?.id ?? "")),
    [railJobs, me?.id],
  );
  const recentJobs = useMemo(
    () =>
      railJobs.filter(
        (j) => !jobNeedsViewerAction(j, me?.id ?? "") && j.workflow !== "workspace_coordination",
      ),
    [railJobs, me?.id],
  );
  if (!me) return null;

  return (
    <nav className="ws-rail" aria-label="Workspace">
      <div className="ws-rail-top">
        <Link to="/workspace/new" className="ws-new-job">
          <PlusIcon />
          New job
        </Link>

        <div className="ws-nav">
          <NavLink
            to="/workspace"
            end
            className={({ isActive }) => (isActive ? "ws-nav-link active" : "ws-nav-link")}
          >
            <MessageIcon />
            Messages
          </NavLink>
          <NavLink
            to="/workspace/jobs"
            className={({ isActive }) => (isActive ? "ws-nav-link active" : "ws-nav-link")}
          >
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
            {queueCount > 0 && (
              <span className="ws-nav-badge" aria-label={`${queueCount} waiting in team queue`}>
                {queueCount}
              </span>
            )}
          </NavLink>
        </div>
      </div>

      <div className="ws-rail-scroll">
        {(entry || directColleagues.length > 0) && (
          <div className="ws-rail-group">
            <span className="eyebrow">People</span>
            {entry && (
              <NavLink
                to={`/workspace/people/${encodeURIComponent(entry.seat)}`}
                className={({ isActive }) => (isActive ? "ws-person-link active" : "ws-person-link")}
              >
                <span className="ws-person-avatar" aria-hidden="true">
                  {workerInitials(entry)}
                </span>
                <span className="ws-person-text">
                  <span className="ws-person-name">{workerColleagueName(entry)}</span>
                  {entry.title ? <span className="ws-person-title">{entry.title}</span> : null}
                </span>
              </NavLink>
            )}
            {directColleagues.map((w) => (
              <NavLink
                key={w.seat}
                to={`/workspace/people/${encodeURIComponent(w.seat)}`}
                className={({ isActive }) => (isActive ? "ws-person-link active" : "ws-person-link")}
              >
                <span className="ws-person-avatar" aria-hidden="true">
                  {workerInitials(w)}
                </span>
                <span className="ws-person-text">
                  <span className="ws-person-name">{workerColleagueName(w)}</span>
                  {w.title ? <span className="ws-person-title">{w.title}</span> : null}
                </span>
              </NavLink>
            ))}
          </div>
        )}

        {needsYouJobs.length > 0 && (
          <div className="ws-rail-group ws-rail-group-attention">
            <span className="eyebrow ws-eyebrow-attention">Needs your action</span>
            {needsYouJobs.map((j) => (
              <RailJobLink
                key={j.instance_id}
                instanceId={j.instance_id}
                seat={j.seat}
                title={j.title}
                detail={pendingActionLabel(j)}
                needsYou
                chatStyle
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
              seat={j.seat}
              title={j.title}
              detail={j.state_label}
              chatStyle
            />
          ))}
          {(jobs.data?.length ?? 0) > 6 && (
            <Link to="/workspace/jobs" className="ws-rail-more">
              View all jobs
            </Link>
          )}
        </div>
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
