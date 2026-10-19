import { when } from "../../lib/ui";
import type { Turn } from "../types";
import styles from "./PersonMessage.module.css";

function textFromTurn(turn: Turn): string {
  return turn.blocks
    .flatMap((b) => (b.kind === "text" ? [b.text] : []))
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
