import { Link } from "react-router";
import { useState } from "react";
import { EmptyState, StatusPill } from "../components";
import { useMyInstances, useWorkflowTitle } from "./useWorkspaceQueries";

type Filter = "active" | "closed";

export default function MyJobsPage() {
  const [filter, setFilter] = useState<Filter>("active");
  const jobs = useMyInstances(filter);
  const workflowTitle = useWorkflowTitle();

  return (
    <>
      <header style={{ display: "flex", flexWrap: "wrap", alignItems: "flex-end", gap: 12 }}>
        <div style={{ flex: "1 1 280px" }}>
          <h1>My jobs</h1>
          <span className="sub">Jobs you started or take part in. Newest activity first.</span>
        </div>
        <div role="tablist" aria-label="Filter" className="ws-filter-tabs">
          {(["active", "closed"] as const).map((f) => (
            <button
              key={f}
              type="button"
              role="tab"
              aria-selected={filter === f}
              className={filter === f ? "ws-filter-tab active" : "ws-filter-tab"}
              onClick={() => setFilter(f)}
            >
              {f === "active" ? "Active" : "Closed"}
            </button>
          ))}
        </div>
      </header>

      {jobs.isLoading && <p className="muted">Loading jobs…</p>}
      {!jobs.isLoading && !jobs.data?.length && (
        <EmptyState title="No jobs here" nextStep="Start one from New job when a digital worker is active." />
      )}
      <ul className="ws-job-list" aria-label="Jobs">
        {jobs.data?.map((j) => (
          <li key={j.instance_id} className="ws-job-card">
            <div style={{ flex: "1 1 320px", minWidth: 0 }}>
              <span className="muted" style={{ fontSize: 12 }}>
                {workflowTitle(j.workflow)} · {j.instance_id}
              </span>
              <h2 style={{ margin: "6px 0", fontSize: 17 }}>{j.title}</h2>
              <StatusPill state={j.state_label} />
            </div>
            <Link to={`/workspace/jobs/${j.instance_id}`} className="btn primary ws-open-job">
              {filter === "active" ? "Continue" : "Open"}
            </Link>
          </li>
        ))}
      </ul>
    </>
  );
}
