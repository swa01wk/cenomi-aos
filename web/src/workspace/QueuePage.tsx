import { useState } from "react";
import { useNavigate } from "react-router";
import { useQueryClient } from "@tanstack/react-query";
import { useSession } from "../app/session";
import { client } from "../api/client";
import { ApiProblemError, type Problem } from "../api/problems";
import { Button, ConflictNotice, EmptyState, ProblemNotice, StatusPill } from "../components";
import { teamLabel } from "../lib/ui";
import { invalidateWorkspaceLists, useQueue, useWorkflowTitle } from "./useWorkspaceQueries";

export default function QueuePage() {
  const { me } = useSession();
  const jobs = useQueue(me?.team);
  const workflowTitle = useWorkflowTitle();
  const [conflict, setConflict] = useState<Problem | null>(null);
  const [problem, setProblem] = useState<Problem | null>(null);

  return (
    <>
      <header style={{ display: "flex", flexWrap: "wrap", alignItems: "flex-end", gap: 12 }}>
        <div style={{ flex: "1 1 280px" }}>
          <h1>Team queue</h1>
          <span className="sub">
            {me ? `${teamLabel(me.team)}. ` : ""}
            Approve to take a job, or reject it. Your comment is posted on the job.
          </span>
        </div>
      </header>

      {conflict && (
        <ConflictNotice
          title={conflict.title}
          detail={conflict.detail}
          onReload={() => {
            setConflict(null);
            void jobs.refetch();
          }}
        />
      )}
      {problem && <ProblemNotice problem={problem} onRetry={() => setProblem(null)} />}

      {jobs.isLoading && <p className="muted">Loading the queue…</p>}
      {jobs.isError && (
        <ProblemNotice
          problem={
            jobs.error instanceof ApiProblemError
              ? jobs.error.problem
              : {
                  type: "about:blank",
                  title: "Could not load the queue",
                  status: 500,
                  code: "internal",
                  detail: String(jobs.error),
                }
          }
          onRetry={() => void jobs.refetch()}
        />
      )}
      {!jobs.isLoading && !jobs.isError && !jobs.data?.length && (
        <EmptyState title="No jobs are waiting" nextStep="When a job needs someone from your team, it appears here." />
      )}
      <ul className="ws-job-list" aria-label="Team queue">
        {jobs.data?.map((job) => (
          <QueueCard
            key={job.instance_id}
            job={job}
            workflowTitle={workflowTitle(job.workflow)}
            onConflict={setConflict}
            onProblem={setProblem}
          />
        ))}
      </ul>
    </>
  );
}

function QueueCard({
  job,
  workflowTitle,
  onConflict,
  onProblem,
}: {
  job: {
    instance_id: string;
    title: string;
    state_label: string;
    version: number;
    claim_role?: string;
  };
  workflowTitle: string;
  onConflict: (problem: Problem) => void;
  onProblem: (problem: Problem | null) => void;
}) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState<"approve" | "reject" | null>(null);
  const note = comment.trim();
  const role = job.claim_role;

  const review = async (decision: "approve" | "reject") => {
    if (!role || !note || busy) return;
    setBusy(decision);
    onProblem(null);
    try {
      const { data, error } = await client.POST("/instances/{id}/claim", {
        params: { path: { id: job.instance_id } },
        body: { role, expected_version: job.version, decision, note },
      });
      if (error) throw error;
      invalidateWorkspaceLists(queryClient);
      if (data && "decision" in data && data.decision === "rejected") return;
      void navigate(`/workspace/jobs/${job.instance_id}`);
    } catch (e) {
      if (e instanceof ApiProblemError) {
        if (e.problem.code === "already_claimed" || e.problem.code === "stale_version") onConflict(e.problem);
        else onProblem(e.problem);
      } else {
        onProblem({
          type: "about:blank",
          title: "Could not update the job",
          status: 500,
          code: "internal",
          detail: String(e),
        });
      }
    } finally {
      setBusy(null);
    }
  };

  return (
    <li className="ws-job-card">
      <div style={{ flex: "1 1 240px", minWidth: 0 }}>
        <span className="muted" style={{ fontSize: 12 }}>
          {workflowTitle} · {job.instance_id}
        </span>
        <h2 style={{ margin: "6px 0", fontSize: 17 }}>{job.title}</h2>
        <StatusPill state={job.state_label} />
      </div>
      <form
        className="ws-queue-actions"
        onSubmit={(e) => {
          e.preventDefault();
          void review("approve");
        }}
      >
        <label>
          <span className="ws-sr-only">Comment for {job.instance_id}</span>
          <textarea
            className="ws-queue-comment"
            value={comment}
            placeholder="Comment"
            maxLength={2000}
            onChange={(e) => setComment(e.target.value)}
          />
        </label>
        <div className="ws-queue-buttons">
          <Button
            type="submit"
            variant="primary"
            disabledReason={!role ? "This job has no role to claim" : !note ? "Write a comment first" : busy ? "Saving" : undefined}
          >
            {busy === "approve" ? "Approving…" : "Approve"}
          </Button>
          <Button
            type="button"
            variant="danger"
            disabledReason={!role ? "This job has no role to claim" : !note ? "Write a comment to reject" : busy ? "Saving" : undefined}
            onClick={() => void review("reject")}
          >
            {busy === "reject" ? "Rejecting…" : "Reject"}
          </Button>
        </div>
      </form>
    </li>
  );
}
