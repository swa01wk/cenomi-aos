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
  if (onOpen) {
    return (
      <button type="button" className={styles.chip} onClick={() => onOpen(block.artifact_id, block.version)}>
        {label}
      </button>
    );
  }
  return <span className={styles.chip}>{label}</span>;
}
