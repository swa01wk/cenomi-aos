import { useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router";
import { useQueryClient } from "@tanstack/react-query";
import { client } from "../api/client";
import { ApiProblemError } from "../api/problems";
import type { Problem } from "../api/problems";
import { Button, EmptyState, ProblemNotice } from "../components";
import { newClientTurnId } from "../components/clientTurnId";
import { invalidateWorkspaceLists, useDigitalWorkers, workspaceKeys } from "./useWorkspaceQueries";
import { SparkleIcon } from "./icons";
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

  const greeter = activeWorkers.find((w) => w.seat === seat) ?? activeWorkers[0]!;

  return (
    <div className={styles.layout}>
      <section aria-label="Start a job" className={styles.main}>
        <div className={styles.hero}>
          <span className={styles.heroMark} aria-hidden="true">
            <SparkleIcon size={28} />
          </span>
          <span className={styles.hello}>Hi, I&apos;m your {greeter.display_name}.</span>
          <h1 className={styles.heroTitle}>
            What do you <span className={styles.heroAccent}>need</span>?
          </h1>
          <p className={styles.heroSub}>
            Pick a workflow, then describe the need in your own words. I&apos;ll ask for anything missing.
          </p>
        </div>

        <fieldset className={styles.workflows}>
          <legend className="ws-sr-only">Workflow</legend>
          {activeWorkers.map((w) =>
            w.workflows.map((wf) => {
              const selected = seat === w.seat && workflow === wf.name;
              return (
                <label key={`${w.seat}-${wf.name}`} className={selected ? styles.cardSelected : styles.card}>
                  <span className={styles.cardHead}>
                    <input
                      type="radio"
                      name="workflow"
                      checked={selected}
                      onChange={() => {
                        setSeat(w.seat);
                        setWorkflow(wf.name);
                      }}
                    />
                    <span className={styles.cardTitle}>{wf.title}</span>
                  </span>
                  <span className={styles.cardText}>{wf.description}</span>
                  <span className={styles.cardMeta}>{w.display_name}</span>
                </label>
              );
            }),
          )}
        </fieldset>

        <div className={styles.need}>
          <label htmlFor="need-text" className={styles.needLabel}>
            Describe the need
          </label>
          <div className={styles.needBox}>
            <textarea
              id="need-text"
              rows={3}
              maxLength={4000}
              value={need}
              placeholder="What you need, where, how much and by when"
              onChange={(e) => setNeed(e.target.value)}
            />
            <Button
              variant="primary"
              disabledReason={
                !seat || !workflow ? "Pick a workflow first" : !need.trim() ? "Describe the need first" : busy ? "Starting…" : undefined
              }
              onClick={() => void start()}
            >
              Start
            </Button>
          </div>
        </div>
        {problem && <ProblemNotice problem={problem} />}
      </section>

      <aside aria-label="How this workflow works" className={styles.aside}>
        <header className={styles.asideHead}>
          <div>
            <div className="eyebrow">Work in progress</div>
            <div className={styles.asideTitle}>{selectedWorkflow?.title ?? "New job"}</div>
          </div>
          <span className="pill">Empty</span>
        </header>
        <div className={styles.asideBody}>
          <p className={styles.asideLead}>
            {selectedWorkflow
              ? selectedWorkflow.description
              : "Pick a workflow on the left. Its documents fill in here as we talk."}
          </p>
          <div className={styles.asideBox}>
            <span style={{ fontWeight: 700 }}>What you&apos;ll see</span>
            <span>
              Progress through each stage and the documents the worker saves for you. Details you cannot see stay with
              other roles.
            </span>
          </div>
        </div>
      </aside>
    </div>
  );
}
