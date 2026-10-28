import { JobStepGuide } from "./JobStepGuide";
import type { StepGuide } from "./stageGuideLogic";
import styles from "./job.module.css";

/** Mirrors the conversation guide when the work panel has no send action. */
export function WorkPanelStageGuide({
  guide,
  live,
  workflowState,
}: {
  guide: StepGuide;
  live: boolean;
  workflowState: string;
}) {
  return (
    <div className={[styles.workPanelStageGuide, live ? styles.workPanelStageGuideLive : ""].filter(Boolean).join(" ")}>
      <JobStepGuide guide={guide} live={live} workflowState={workflowState} />
    </div>
  );
}
