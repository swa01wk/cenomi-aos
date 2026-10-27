import { useEffect, useState } from "react";
import styles from "./ThinkingStatus.module.css";

/** Rotating status while the model has not sent the first words of a reply. */
const PHRASES = [
  "Thinking",
  "Meticulating",
  "Pondering",
  "Considering",
  "Reasoning",
  "Untangling",
  "Formulating",
  "Reflecting",
  "Composing",
  "Weighing this",
];

const PHRASE_MS = 2400;
const DOT_MS = 380;
/** Displayed time moves one second for every 1.5 seconds that pass. */
const TICK_MS = 1500;
const SLOW_AFTER_S = 90;

export function formatElapsed(seconds: number): string {
  if (seconds < 60) return `${seconds}s`;
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}m ${s.toString().padStart(2, "0")}s`;
}

export function ThinkingStatus() {
  const [phraseIndex, setPhraseIndex] = useState(0);
  const [dots, setDots] = useState(1);
  const [elapsed, setElapsed] = useState(0);
  const [motion, setMotion] = useState(true);

  useEffect(() => {
    const reduce =
      typeof window.matchMedia === "function" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    setMotion(!reduce);
    const clock = window.setInterval(() => setElapsed((n) => n + 1), TICK_MS);
    if (reduce) return () => window.clearInterval(clock);
    const phrases = window.setInterval(() => {
      setPhraseIndex((n) => (n + 1) % PHRASES.length);
    }, PHRASE_MS);
    const tick = window.setInterval(() => {
      setDots((n) => (n % 3) + 1);
    }, DOT_MS);
    return () => {
      window.clearInterval(clock);
      window.clearInterval(phrases);
      window.clearInterval(tick);
    };
  }, []);

  const phrase = PHRASES[phraseIndex] ?? PHRASES[0];
  return (
    <div className={styles.wrap} role="status" aria-live="polite">
      <p className={styles.row}>
        <span key={phrase} className={motion ? styles.phrase : styles.phraseStill}>
          {phrase}
        </span>
        <span className={styles.dots} aria-hidden="true">
          {".".repeat(motion ? dots : 3)}
        </span>
        <span className={styles.elapsed}>{formatElapsed(elapsed)}</span>
      </p>
      {elapsed >= SLOW_AFTER_S && (
        <p className={styles.slow}>
          This is taking longer than usual. If nothing changes in a few minutes, send your message again.
        </p>
      )}
    </div>
  );
}
