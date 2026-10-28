import { useEffect, useState } from "react";
import type { ToolActivity } from "../../components/types";
import { WaitingDots } from "../../lib/WaitingDots";
import { buildAgentWorkStatus, formatElapsed } from "./agentWorkPlan";
import styles from "./AgentWorkStatus.module.css";

const TICK_MS = 1000;
const SLOW_AFTER_S = 90;

export { formatElapsed };

export function AgentWorkStatus({
  workflowState,
  toolActivity,
  isFirstExchange,
}: {
  workflowState: string;
  toolActivity?: ToolActivity;
  isFirstExchange: boolean;
}) {
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    const clock = window.setInterval(() => setElapsed((n) => n + 1), TICK_MS);
    return () => window.clearInterval(clock);
  }, []);

  const model = buildAgentWorkStatus({
    workflowState,
    toolActivity,
    isFirstExchange,
    elapsedSec: elapsed,
  });

  return (
    <div className={styles.wrap} role="status" aria-live="polite">
      <p className={styles.headline}>
        {model.headline}
        <WaitingDots />
      </p>
      <ol className={styles.steps}>
        {model.steps.map((step) => (
          <li
            key={step.label}
            className={
              step.status === "current"
                ? styles.stepCurrent
                : step.status === "done"
                  ? styles.stepDone
                  : styles.stepUpcoming
            }
          >
            {step.label}
          </li>
        ))}
      </ol>
      {model.expectation ? <p className={styles.expectation}>{model.expectation}</p> : null}
      {model.asyncHint ? (
        <p className={styles.asyncHint}>
          You can leave this page or send another message later. The worker keeps going until this step finishes.
        </p>
      ) : null}
      <p className={styles.meta}>
        <span className={styles.elapsed}>{formatElapsed(model.elapsedSec)}</span>
        {toolActivity && toolActivity.state !== "completed" ? (
          <span className={styles.toolState}>{toolActivity.state.replace("_", " ")}</span>
        ) : null}
      </p>
      {elapsed >= SLOW_AFTER_S ? (
        <p className={styles.slow}>
          This is taking longer than usual. If nothing changes in a few minutes, send your message again or retry the
          failed step if one appears.
        </p>
      ) : null}
    </div>
  );
}
