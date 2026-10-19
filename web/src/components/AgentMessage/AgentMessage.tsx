import { initials } from "../../lib/ui";
import { ArtifactChip } from "../ArtifactChip/ArtifactChip";
import { RefusalNotice } from "../RefusalNotice/RefusalNotice";
import { SourceChip } from "../SourceChip/SourceChip";
import type { Block, Turn } from "../types";
import styles from "./AgentMessage.module.css";

function isTextBlock(b: Block): b is Extract<Block, { text: string }> {
  return "text" in b && typeof (b as { text?: string }).text === "string";
}

export function AgentMessage({
  turn,
  onOpenArtifact,
  onOpenSource,
  decisionHref,
}: {
  turn: Turn;
  onOpenArtifact?: (artifactId: string, version: number) => void;
  onOpenSource?: (sourceRef: string) => void;
  decisionHref?: (decisionId: string) => string | undefined;
}) {
  return (
    <div className={styles.row}>
      <span className={styles.avatar} aria-hidden="true">
        {initials(turn.author.name)}
      </span>
      <div className={styles.body}>
        {turn.blocks.map((block, i) => (
          <BlockView
            key={i}
            block={block}
            onOpenArtifact={onOpenArtifact}
            onOpenSource={onOpenSource}
            decisionHref={decisionHref}
          />
        ))}
      </div>
    </div>
  );
}

function BlockView({
  block,
  onOpenArtifact,
  onOpenSource,
  decisionHref,
}: {
  block: Block;
  onOpenArtifact?: (artifactId: string, version: number) => void;
  onOpenSource?: (sourceRef: string) => void;
  decisionHref?: (decisionId: string) => string | undefined;
}) {
  if ("text" in block && "tone" in block) {
    const tone = block.tone ?? "info";
    const toneClass =
      tone === "warn" ? styles.noticeWarn : tone === "bad" ? styles.noticeBad : tone === "ok" ? styles.noticeOk : styles.noticeInfo;
    return <p className={`${styles.notice} ${toneClass}`}>{block.text}</p>;
  }
  if (isTextBlock(block)) {
    return <p className={styles.text}>{block.text}</p>;
  }
  if ("artifact_id" in block) {
    return (
      <div className={styles.chips}>
        <ArtifactChip block={block} onOpen={onOpenArtifact} />
      </div>
    );
  }
  if ("source_ref" in block) {
    return (
      <div className={styles.chips}>
        <SourceChip block={block} onOpen={onOpenSource} />
      </div>
    );
  }
  if ("pending_id" in block) {
    return (
      <span className={styles.pending} data-testid="pending-ref-placeholder">
        Waiting for input…
      </span>
    );
  }
  if ("title" in block && "decision_id" in block) {
    const href = decisionHref?.(block.decision_id);
    return (
      <RefusalNotice
        title={block.title}
        detail={block.detail}
        rule={block.rule}
        decisionId={block.decision_id}
        decisionHref={href}
      />
    );
  }
  return null;
}
