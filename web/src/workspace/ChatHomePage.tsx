import { useMemo, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router";
import { useQueryClient } from "@tanstack/react-query";
import { ApiProblemError } from "../api/problems";
import type { Problem } from "../api/problems";
import { Button, EmptyState, ProblemNotice } from "../components";
import { newClientTurnId } from "../components/clientTurnId";
import { useDigitalWorkers } from "./useWorkspaceQueries";
import { repeatOrderFirstMessage } from "./repeatOrder";
import { personChatPath } from "./jobPaths";
import { workerColleagueName, workerInitials } from "./persona";
import {
  entryColleague,
  isFormalRfpRequest,
  pickSpecialistWorker,
  routeWorkflowName,
  shouldOpenSpecialistJob,
  specialistColleagues,
} from "./workspaceEntry";
import { useSession } from "../app/session";
import { startCoordinatorThread, startSpecialistFromIntake } from "./startJobs";
import styles from "./chatHome.module.css";

type ChatHomePageProps = {
  /** When true, the first message always opens a coordinator thread (New job). */
  newJob?: boolean;
};

export default function ChatHomePage({ newJob = false }: ChatHomePageProps) {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const repeatFrom = searchParams.get("repeat")?.trim() || null;
  const queryClient = useQueryClient();
  const { me } = useSession();
  const workers = useDigitalWorkers();
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<Problem | null>(null);
  const [routingNote, setRoutingNote] = useState<string | null>(null);
  const idempotencyRef = useRef<string | null>(null);

  const activeWorkers = useMemo(
    () => workers.data?.filter((w) => w.state === "ACTIVE") ?? [],
    [workers.data],
  );
  const entry = useMemo(() => entryColleague(activeWorkers), [activeWorkers]);

  const send = async () => {
    const text = message.trim();
    if ((!repeatFrom && !text) || busy) return;
    if (!idempotencyRef.current) idempotencyRef.current = newClientTurnId();
    setBusy(true);
    setProblem(null);
    const bodyText = repeatFrom ? repeatOrderFirstMessage(repeatFrom, text) : text;
    try {
      if (repeatFrom) {
        setRoutingNote("Opening the repeat with your specialist…");
        const data = await startSpecialistFromIntake(bodyText, idempotencyRef.current, queryClient, {
          repeat_from_instance_id: repeatFrom,
        });
        idempotencyRef.current = null;
        void navigate(personChatPath(data.seat, data.instance_id));
        return;
      }
      const specialist = pickSpecialistWorker(bodyText, activeWorkers);
      const directToSpecialist =
        newJob &&
        Boolean(specialist) &&
        shouldOpenSpecialistJob(bodyText, activeWorkers) &&
        (me?.roles.includes("sourcing_user") || isFormalRfpRequest(bodyText));
      if (directToSpecialist && specialist) {
        const wf = routeWorkflowName(bodyText, activeWorkers);
        setRoutingNote(
          wf === "sourcing_rfp"
            ? `Starting a full RFP with ${workerColleagueName(specialist)}…`
            : `Opening with ${workerColleagueName(specialist)}…`,
        );
        const data = await startSpecialistFromIntake(bodyText, idempotencyRef.current, queryClient, {
          seat: specialist.seat,
        });
        idempotencyRef.current = null;
        void navigate(personChatPath(data.seat, data.instance_id));
        return;
      }
      if (!entry) {
        throw new Error("No entry colleague");
      }
      setRoutingNote(`Opening chat with ${workerColleagueName(entry)}…`);
      const data = await startCoordinatorThread(entry, bodyText || "Hello", idempotencyRef.current, queryClient);
      idempotencyRef.current = null;
      void navigate(personChatPath(data.seat, data.instance_id));
    } catch (e) {
      setRoutingNote(null);
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

  if (workers.isLoading) return <p className="muted">Loading…</p>;

  if (!entry) {
    return (
      <EmptyState
        title="No one to message yet"
        nextStep="When your workspace coordinator is active, you can start here."
      />
    );
  }

  const name = workerColleagueName(entry);
  const specialists = specialistColleagues(activeWorkers);
  const starters = newJob
    ? [
        "Hi — I need help with a purchase",
        "We need equipment for a new site",
        "Can you help me get quotes for laptops?",
        "Run an RFP for a new customer web service and API",
      ]
    : ["Hey, how are you?", "I need to order supplies for my team"];

  return (
    <div className={styles.shell} aria-label="Workspace chat">
      <header className={styles.header}>
        <div className={styles.headerInner}>
          <h1>{newJob ? "New job" : "What can we help with?"}</h1>
          <p>
            {newJob
              ? "Tell your workspace coordinator what you need. They will bring in the right digital colleague when it is time."
              : "Message your workspace coordinator in plain language. They route detailed requests to the right colleague and stay with you for everything else."}
          </p>
        </div>
      </header>

      <div className={styles.content}>
        <div className={styles.primary}>
          <div className={styles.body}>
            <div className={styles.welcome}>
              <span className={styles.welcomeAvatar} aria-hidden="true">
                {workerInitials(entry)}
              </span>
              <p className={styles.welcomeLead}>
                Start with <strong>{name}</strong>
                {entry.title ? ` · ${entry.title}` : ""}
              </p>
              <p className={styles.welcomeHint}>Say hello, or describe what you need in plain language.</p>
              <div className={styles.suggestions} role="list" aria-label="Example messages">
                {starters.map((line) => (
                  <button
                    key={line}
                    type="button"
                    className={styles.suggestion}
                    disabled={busy}
                    onClick={() => setMessage(line)}
                  >
                    {line}
                  </button>
                ))}
              </div>
            </div>
          </div>
        </div>

        <aside className={styles.aside} aria-label="How this works">
          <span className="eyebrow">How it works</span>
          <ol className={styles.steps}>
            <li>Chat with your coordinator like a colleague.</li>
            <li>When your request is clear, they connect you with a specialist.</li>
            <li>Track progress in one thread and the work panel.</li>
          </ol>
          {specialists.length > 0 && (
            <>
              <span className="eyebrow" style={{ marginTop: 20 }}>
                Specialists on your team
              </span>
              <ul className={styles.specialistList}>
                {specialists.map((w) => (
                  <li key={w.seat}>
                    <span className={styles.specialistName}>{workerColleagueName(w)}</span>
                    {w.title ? <span className={styles.specialistTitle}>{w.title}</span> : null}
                  </li>
                ))}
              </ul>
            </>
          )}
        </aside>
      </div>

      <div className={styles.composerDock}>
        <div className={styles.composerBox}>
          <label htmlFor="intake-message" className="ws-sr-only">
            Message
          </label>
          <textarea
            id="intake-message"
            className={styles.composerInput}
            rows={2}
            maxLength={4000}
            placeholder={`Message ${name}…`}
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                void send();
              }
            }}
          />
          <div className={styles.composerActions}>
            <Button
              variant="primary"
              disabledReason={
                !repeatFrom && !message.trim() ? "Write a message first" : busy ? "Sending…" : undefined
              }
              onClick={() => void send()}
            >
              Send
            </Button>
          </div>
        </div>
        {routingNote && !problem && <p className={styles.routingNote}>{routingNote}</p>}
        {problem && <ProblemNotice problem={problem} />}
      </div>
    </div>
  );
}
