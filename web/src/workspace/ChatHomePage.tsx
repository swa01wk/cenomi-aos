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
import { entryColleague } from "./workspaceEntry";
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

  return (
    <div className={styles.shell} aria-label="Workspace chat">
      <header className={styles.header}>
        <h1>{newJob ? "New job" : "What can we help with?"}</h1>
        <p>
          {newJob
            ? "Tell your workspace coordinator what you need. They will bring in the right digital colleague when it is time."
            : "Message your workspace coordinator in plain language. They route detailed requests to the right colleague and stay with you for everything else."}
        </p>
      </header>

      <div className={styles.body}>
        <div>
          <span className="eyebrow">Your coordinator</span>
          <div className={styles.peopleRow}>
            <div className={styles.personChip} aria-current="true">
              <span className={styles.avatar} aria-hidden="true">
                {workerInitials(entry)}
              </span>
              <span>
                {name}
                {entry.title ? (
                  <>
                    <br />
                    <span style={{ fontWeight: 500, fontSize: 12, color: "var(--ink-3)" }}>{entry.title}</span>
                  </>
                ) : null}
              </span>
            </div>
          </div>
        </div>
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
