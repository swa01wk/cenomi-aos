import { WaitingDots } from "../../lib/WaitingDots";
import type { StepGuide } from "./stageGuideLogic";
import { stepGuideShowsWaitingDots } from "./stageGuideLogic";
import styles from "./JobStepGuide.module.css";

export function JobStepGuide({
  guide,
  live = false,
  workflowState,
}: {
  guide: StepGuide;
  live?: boolean;
  workflowState?: string;
}) {
  const waitingDots = stepGuideShowsWaitingDots(guide, workflowState);
  const liveGuide = live && guide.kind !== "complete";

  return (
    <div
      className={[styles.guide, styles[`guide_${guide.kind}`], liveGuide ? styles.guide_live : ""]
        .filter(Boolean)
        .join(" ")}
      role="status"
      aria-live="polite"
    >
      <p className={styles.title}>
        {guide.title}
        {waitingDots ? <WaitingDots /> : null}
      </p>
      <p className={styles.detail}>{guide.detail}</p>
      {guide.footnote ? <p className={styles.footnote}>{guide.footnote}</p> : null}
    </div>
  );
}
