import { toneForState } from "../statusTone";
import styles from "./StatusPill.module.css";

export function StatusPill({ state }: { state: string }) {
  const tone = toneForState(state);
  return <span className={`${styles.pill} ${styles[tone]}`}>{state}</span>;
}
