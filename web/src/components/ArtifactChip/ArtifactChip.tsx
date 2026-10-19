import type { Block } from "../types";
import styles from "./ArtifactChip.module.css";

type ArtifactBlock = Extract<Block, { artifact_id: string }>;

export function ArtifactChip({
  block,
  onOpen,
}: {
  block: ArtifactBlock;
  onOpen?: (artifactId: string, version: number) => void;
}) {
  const label = `${block.label} v${block.version}`;
  const body = (
    <>
      <svg className={styles.docIcon} viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.4" aria-hidden="true">
        <path d="M3 1.5h4l2 2v7H3z" />
      </svg>
      {label}
    </>
  );
  if (onOpen) {
    return (
      <button type="button" className={styles.chip} onClick={() => onOpen(block.artifact_id, block.version)}>
        {body}
      </button>
    );
  }
  return <span className={styles.chip}>{body}</span>;
}
