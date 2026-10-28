import { useShell } from "../ShellContext";
import { toneForState } from "../statusTone";
import styles from "./StatusPill.module.css";

export function StatusPill({ state }: { state: string }) {
  const tone = toneForState(state);
  const shell = useShell();
  return (
    <span className={`${styles.pill} ${styles[tone]} ${shell === "workspace" ? styles.workspace : ""}`}>{state}</span>
  );
}
