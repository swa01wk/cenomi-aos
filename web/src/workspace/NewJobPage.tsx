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

const EXAMPLE_NEED = `e.g. I need 100 MacBook M4 laptops (13-inch, 8GB, 256GB, Space Grey) with Arabic keyboards, delivered to Al Nakheel Mall by 20 December.`;

export default function NewJobPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const workers = useDigitalWorkers();
  const [need, setNeed] = useState("");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<Problem | null>(null);
  const idempotencyRef = useRef<string | null>(null);

  const activeWorkers = workers.data?.filter((w) => w.state === "ACTIVE") ?? [];

  const startTarget = useMemo(() => {
    for (const w of activeWorkers) {
      const wf = w.workflows[0];
      if (wf) {
        return { seat: w.seat, workflow: wf.name, worker: w };
      }
    }
    return null;
  }, [activeWorkers]);

  const start = async () => {
    if (!startTarget || !need.trim() || busy) return;
    if (!idempotencyRef.current) idempotencyRef.current = newClientTurnId();
    setBusy(true);
    setProblem(null);
    try {
      const { data, error } = await client.POST("/instances", {
        params: { header: { "Idempotency-Key": idempotencyRef.current } },
        body: {
          seat: startTarget.seat,
          workflow: startTarget.workflow,
          first_message: need.trim(),
        },
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

  if (!activeWorkers.length || !startTarget) {
    return (
      <EmptyState
        title="No digital worker available"
        nextStep="When a Seat is active for your area, you can start a new request here."
      />
    );
  }

  const greeter = startTarget.worker;

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
            Describe the request in your own words. I&apos;ll ask for anything missing and take it from there.
          </p>
        </div>

        <div className={styles.need}>
          <label htmlFor="need-text" className={styles.needLabel}>
            Your request
          </label>
          <div className={styles.needBox}>
            <textarea
              id="need-text"
              className={styles.needInput}
              rows={4}
              maxLength={4000}
              value={need}
              placeholder={EXAMPLE_NEED}
              autoFocus
              aria-describedby="need-example-hint"
              onChange={(e) => setNeed(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) void start();
              }}
            />
            <Button
              variant="primary"
              disabledReason={!need.trim() ? "Describe the need first" : busy ? "Starting…" : undefined}
              onClick={() => void start()}
            >
              Start
            </Button>
          </div>
          <p id="need-example-hint" className={styles.needHint}>
            Replace the example with your own item, quantity, location and deadline.
          </p>
        </div>
        {problem && <ProblemNotice problem={problem} />}
      </section>

      <aside aria-label="How a new job works" className={styles.aside}>
        <header className={styles.asideHead}>
          <div>
            <div className="eyebrow">Work in progress</div>
            <div className={styles.asideTitle}>Your request</div>
          </div>
          <span className="pill">Empty</span>
        </header>
        <div className={styles.asideBody}>
          <p className={styles.asideLead}>
            After you start, this panel fills with documents the digital worker saves: briefs, ranked lists, outbound
            messages, comparisons, and more.
          </p>
          <div className={styles.asideBox}>
            <span style={{ fontWeight: 700 }}>What you&apos;ll see</span>
            <span>
              Progress through each stage and the artifacts for your role. Details meant for other participants stay
              with them.
            </span>
          </div>
        </div>
      </aside>
    </div>
  );
}
