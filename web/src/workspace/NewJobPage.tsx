import { useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router";
import { useQueryClient } from "@tanstack/react-query";
import { client } from "../api/client";
import { ApiProblemError } from "../api/problems";
import type { Problem } from "../api/problems";
import { Button, EmptyState, ProblemNotice } from "../components";
import { newClientTurnId } from "../components/clientTurnId";
import { invalidateWorkspaceLists, useDigitalWorkers, workspaceKeys } from "./useWorkspaceQueries";
import styles from "./newJob.module.css";

export default function NewJobPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const workers = useDigitalWorkers();
  const [seat, setSeat] = useState<string>("");
  const [workflow, setWorkflow] = useState<string>("");
  const [need, setNeed] = useState("");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<Problem | null>(null);
  const idempotencyRef = useRef<string | null>(null);

  const activeWorkers = workers.data?.filter((w) => w.state === "ACTIVE") ?? [];

  const workflows = useMemo(() => {
    const w = activeWorkers.find((x) => x.seat === seat);
    return w?.workflows ?? [];
  }, [activeWorkers, seat]);

  const selectedWorkflow = workflows.find((w) => w.name === workflow);

  const start = async () => {
    if (!seat || !workflow || !need.trim() || busy) return;
    if (!idempotencyRef.current) idempotencyRef.current = newClientTurnId();
    setBusy(true);
    setProblem(null);
    try {
      const { data, error } = await client.POST("/instances", {
        params: { header: { "Idempotency-Key": idempotencyRef.current } },
        body: { seat, workflow, first_message: need.trim() },
      });
      if (error) throw error;
      if (!data) throw new Error("No snapshot returned");
      idempotencyRef.current = null;
      queryClient.setQueryData(workspaceKeys.instance(data.instance_id), data);
      invalidateWorkspaceLists(queryClient);
      void navigate(`/workspace/jobs/${data.instance_id}`);
    } catch (e) {
      if (e instanceof ApiProblemError) setProblem(e.problem);
      else
        setProblem({
          type: "about:blank",
          title: "Could not start",
          detail: String(e),
          status: 500,
          code: "internal",
        });
    } finally {
      setBusy(false);
    }
  };

  if (workers.isLoading) return <p className="muted">Loading digital workers…</p>;

  if (!activeWorkers.length) {
    return (
      <EmptyState
        title="No digital worker available"
        nextStep="When a Seat is active for your area, it appears here and you can start the workflows it offers."
      />
    );
  }

  return (
    <div className={styles.layout}>
      <section aria-label="Start a job" className={styles.main}>
        <div>
          <h1>What do you need?</h1>
          <p className="sub">
            Pick a workflow, then describe the need in your own words. The digital worker asks for anything missing.
          </p>
        </div>

        <fieldset className={styles.workflows}>
          <legend style={{ position: "absolute", width: 1, height: 1, overflow: "hidden" }}>Workflow</legend>
          {activeWorkers.map((w) =>
            w.workflows.map((wf) => {
              const selected = seat === w.seat && workflow === wf.name;
              return (
                <label key={`${w.seat}-${wf.name}`} className={selected ? styles.cardSelected : styles.card}>
                  <span style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <input
                      type="radio"
                      name="workflow"
                      checked={selected}
                      onChange={() => {
                        setSeat(w.seat);
                        setWorkflow(wf.name);
                      }}
                    />
                    <span style={{ fontWeight: 600 }}>{wf.title}</span>
                  </span>
                  <span className="sub" style={{ fontSize: 13 }}>
                    {wf.description}
                  </span>
                  <span className="muted" style={{ fontSize: 12 }}>
                    {w.display_name}
                  </span>
                </label>
              );
            }),
          )}
        </fieldset>

        <div className={styles.need}>
          <label htmlFor="need-text">Describe the need</label>
          <textarea
            id="need-text"
            rows={4}
            maxLength={4000}
            value={need}
            onChange={(e) => setNeed(e.target.value)}
          />
          <div className={styles.actions}>
            <Button variant="primary" disabledReason={!seat || !workflow || !need.trim() ? "Describe the need first" : busy ? "Starting…" : undefined} onClick={() => void start()}>
              Start
            </Button>
          </div>
        </div>
        {problem && <ProblemNotice problem={problem} />}
      </section>

      {selectedWorkflow && (
        <aside aria-label="How this workflow works" className={styles.aside}>
          <h2 style={{ margin: 0, fontSize: 16 }}>How it works</h2>
          <p className="sub" style={{ fontSize: 13 }}>
            {selectedWorkflow.description}
          </p>
          <div className={styles.asideBox}>
            <span style={{ fontWeight: 500 }}>What you&apos;ll see</span>
            <span className="sub" style={{ fontSize: 13 }}>
              Progress through each stage and the documents the worker saves for you. Details you cannot see stay with
              other roles.
            </span>
          </div>
        </aside>
      )}
    </div>
  );
}
