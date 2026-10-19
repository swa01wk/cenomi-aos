import { when } from "../../lib/ui";
import type { Turn } from "../types";
import styles from "./PersonMessage.module.css";

function textFromTurn(turn: Turn): string {
  return turn.blocks
    .filter((b): b is Extract<typeof b, { text: string }> => "text" in b && typeof b.text === "string" && !("tone" in b))
    .map((b) => b.text)
    .join("\n");
}

export function PersonMessage({ turn }: { turn: Turn }) {
  return (
    <div className={styles.wrap}>
      <div className={styles.bubble}>
        <p className={styles.text}>{textFromTurn(turn)}</p>
        <div className={styles.meta}>
          {turn.author.name} · {when(turn.at)}
        </div>
      </div>
    </div>
  );
}
