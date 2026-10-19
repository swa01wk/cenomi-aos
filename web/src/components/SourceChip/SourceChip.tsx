import type { Block } from "../types";
import styles from "./SourceChip.module.css";

type SourceBlock = Extract<Block, { source_ref: string }>;

export function SourceChip({
  block,
  onOpen,
}: {
  block: SourceBlock;
  onOpen?: (sourceRef: string) => void;
}) {
  if (onOpen) {
    return (
      <button type="button" className={styles.chip} onClick={() => onOpen(block.source_ref)}>
        {block.label}
      </button>
    );
  }
  return <span className={styles.chip}>{block.label}</span>;
}
