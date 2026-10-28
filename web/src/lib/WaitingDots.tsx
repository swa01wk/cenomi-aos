import { useEffect, useState } from "react";
import styles from "./WaitingDots.module.css";

/** Cycles … → .. → . → … so in-progress copy does not look frozen. */
const FRAMES = ["…", "..", ".", "…"] as const;

export function WaitingDots({ intervalMs = 480 }: { intervalMs?: number }) {
  const [frame, setFrame] = useState(0);
  const [reducedMotion, setReducedMotion] = useState(false);

  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    const sync = () => setReducedMotion(mq.matches);
    sync();
    mq.addEventListener("change", sync);
    return () => mq.removeEventListener("change", sync);
  }, []);

  useEffect(() => {
    if (reducedMotion) return;
    const id = window.setInterval(() => setFrame((n) => (n + 1) % FRAMES.length), intervalMs);
    return () => window.clearInterval(id);
  }, [intervalMs, reducedMotion]);

  return (
    <span className={styles.dots} aria-hidden="true">
      {reducedMotion ? "…" : FRAMES[frame]}
    </span>
  );
}
