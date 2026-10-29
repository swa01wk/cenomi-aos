import { useRef, useState } from "react";
import { Navigate, useNavigate, useParams } from "react-router";
import { useQueryClient } from "@tanstack/react-query";
import { ApiProblemError } from "../api/problems";
import type { Problem } from "../api/problems";
import { Button, EmptyState, ProblemNotice } from "../components";
import { newClientTurnId } from "../components/clientTurnId";
import { invalidateWorkspaceLists, useDigitalWorkers, useMyInstances, workspaceKeys } from "./useWorkspaceQueries";
import { personChatPath } from "./jobPaths";
import { workerColleagueName, workerInitials } from "./persona";
import { coordinationWorkflow, entryColleague, isEntryColleague } from "./workspaceEntry";
import { openChatInstanceForSeat } from "./openPersonChat";
import { startCoordinatorThread, startSpecialistFromIntake } from "./startJobs";
import styles from "./employeeHub.module.css";

export default function EmployeeHubPage() {
  const { seat = "" } = useParams();
  const decodedSeat = decodeURIComponent(seat);
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const workers = useDigitalWorkers();
  const jobs = useMyInstances();
  const worker = workers.data?.find((w) => w.seat === decodedSeat);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<Problem | null>(null);
  const idempotencyRef = useRef<string | null>(null);

  const openInstanceId =
    worker && jobs.data ? openChatInstanceForSeat(decodedSeat, jobs.data, worker) : undefined;

  const startThread = async () => {
    const text = message.trim();
    if (!text || busy || !worker) return;
    if (!idempotencyRef.current) idempotencyRef.current = newClientTurnId();
    setBusy(true);
    setProblem(null);
    try {
      let data;
      if (isEntryColleague(worker)) {
        const entry = entryColleague(workers.data?.filter((w) => w.state === "ACTIVE") ?? []);
        if (!entry || !coordinationWorkflow(entry)) throw new Error("No entry colleague");
        data = await startCoordinatorThread(entry, text, idempotencyRef.current, queryClient);
      } else {
        data = await startSpecialistFromIntake(text, idempotencyRef.current, queryClient, {
          seat: worker.seat,
        });
      }
      idempotencyRef.current = null;
      queryClient.setQueryData(workspaceKeys.instance(data.instance_id), data);
      invalidateWorkspaceLists(queryClient);
      void navigate(personChatPath(worker.seat, data.instance_id));
    } catch (e) {
      if (e instanceof ApiProblemError) setProblem(e.problem);
      else
        setProblem({
          type: "about:blank",
          title: "Could not send",
          detail: String(e),
          status: 500,
          code: "internal",
        });
    } finally {
      setBusy(false);
    }
  };

  if (workers.isLoading || jobs.isLoading) return <p className="muted">Loading…</p>;

  if (!worker) {
    return (
      <EmptyState title="Colleague not found" nextStep="Use Messages in the sidebar to start again." />
    );
  }

  if (openInstanceId) {
    return <Navigate to={personChatPath(decodedSeat, openInstanceId)} replace />;
  }

  const name = workerColleagueName(worker);
  const hubHint = isEntryColleague(worker)
    ? "Chat with your workspace coordinator. When your request is clear, you will continue with the right specialist in the same way — one conversation at a time."
    : "Message this colleague directly. One open chat at a time; start below when you are ready.";

  return (
    <div className={styles.shell}>
      <header className={styles.top}>
        <span className={styles.avatar} aria-hidden="true">
          {workerInitials(worker)}
        </span>
        <div>
          <h1>{name}</h1>
          <p>{worker.title || "Digital colleague"}</p>
          <p className="muted" style={{ marginTop: 8, maxWidth: 520 }}>
            {hubHint}
          </p>
        </div>
      </header>

      <div className={styles.threads} aria-label="Conversation">
        <p className="muted">No open chat yet. Send a message to start.</p>
      </div>

      <div className={styles.composerDock}>
        <label htmlFor="dm-message" className="ws-sr-only">
          Message {name}
        </label>
        <textarea
          id="dm-message"
          className={styles.composerInput}
          rows={2}
          maxLength={4000}
          placeholder={`Message ${name}`}
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              void startThread();
            }
          }}
        />
        <div className={styles.composerRow}>
          <Button
            variant="primary"
            disabledReason={!message.trim() ? "Write a message first" : busy ? "Sending…" : undefined}
            onClick={() => void startThread()}
          >
            Send
          </Button>
        </div>
        {problem && <ProblemNotice problem={problem} />}
      </div>
    </div>
  );
}
