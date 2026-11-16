import { when } from "../../lib/ui";
import type { Turn } from "../types";
import styles from "./PersonMessage.module.css";

function textFromTurn(turn: Turn): string {
  return turn.blocks
    .flatMap((b) => (b.kind === "text" ? [b.text] : []))
    .join("\n");
}

export function PersonMessage({ turn, highlighted = false }: { turn: Turn; highlighted?: boolean }) {
  return (
    <div className={styles.wrap}>
      <div className={[styles.bubble, highlighted ? styles.bubbleQuoted : ""].filter(Boolean).join(" ")}>
        <p className={styles.text}>{textFromTurn(turn)}</p>
        <div className={styles.meta}>
          {turn.author.name} · {when(turn.at)}
        </div>
      </div>
    </div>
  );
}
