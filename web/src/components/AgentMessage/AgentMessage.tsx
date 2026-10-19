import { initials } from "../../lib/ui";
import { ArtifactChip } from "../ArtifactChip/ArtifactChip";
import { RefusalNotice } from "../RefusalNotice/RefusalNotice";
import { SourceChip } from "../SourceChip/SourceChip";
import type { Block, Turn } from "../types";
import styles from "./AgentMessage.module.css";

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
  switch (block.kind) {
    case "text":
      return <p className={styles.text}>{block.text}</p>;
    case "notice": {
      const tone = block.tone ?? "info";
      const toneClass =
        tone === "warn" ? styles.noticeWarn : tone === "bad" ? styles.noticeBad : tone === "ok" ? styles.noticeOk : styles.noticeInfo;
      return <p className={`${styles.notice} ${toneClass}`}>{block.text}</p>;
    }
    case "artifact_chip":
      return (
        <div className={styles.chips}>
          <ArtifactChip block={block} onOpen={onOpenArtifact} />
        </div>
      );
    case "source_chip":
      return (
        <div className={styles.chips}>
          <SourceChip block={block} onOpen={onOpenSource} />
        </div>
      );
    case "pending_ref":
      // M2 renders the pending item (DecisionCard) here.
      return (
        <span className={styles.pending} data-testid="pending-ref-placeholder">
          Waiting for input…
        </span>
      );
    case "refusal":
      return (
        <RefusalNotice
          title={block.title}
          detail={block.detail}
          rule={block.rule}
          decisionId={block.decision_id}
          decisionHref={decisionHref?.(block.decision_id)}
        />
      );
  }
  return null;
}
