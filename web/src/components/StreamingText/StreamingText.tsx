import type { MessageDelta } from "../types";
import { joinDeltas } from "./joinDeltas";
import styles from "./StreamingText.module.css";

export { joinDeltas } from "./joinDeltas";

export function StreamingText({
  turnId,
  deltas,
  showCaret,
}: {
  turnId: string;
  deltas: MessageDelta[];
  showCaret?: boolean;
}) {
  const relevant = deltas.filter((d) => d.turn_id === turnId);
  const text = joinDeltas(relevant);
  return (
    <span className={styles.text} data-turn-id={turnId}>
      {text}
      {showCaret && <span className={styles.caret} aria-hidden="true" />}
    </span>
  );
}
