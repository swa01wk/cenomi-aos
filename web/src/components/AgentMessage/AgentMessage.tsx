import { type ReactNode } from "react";
import { initials } from "../../lib/ui";
import { ArtifactChip } from "../ArtifactChip/ArtifactChip";
import { RefusalNotice } from "../RefusalNotice/RefusalNotice";
import { SourceChip } from "../SourceChip/SourceChip";
import type { Block, Turn } from "../types";
import styles from "./AgentMessage.module.css";

type ChipBlockData = Extract<Block, { kind: "artifact_chip" }> | Extract<Block, { kind: "source_chip" }>;

function isChipBlock(block: Block): block is ChipBlockData {
  return block.kind === "artifact_chip" || block.kind === "source_chip";
}

export function AgentMessage({
  turn,
  onOpenArtifact,
  onOpenSource,
  decisionHref,
  avatar,
  renderPending,
}: {
  turn: Turn;
  onOpenArtifact?: (artifactId: string, version: number) => void;
  onOpenSource?: (sourceRef: string) => void;
  decisionHref?: (decisionId: string) => string | undefined;
  /** Replaces the author's initials, e.g. with the shell's Seat mark. */
  avatar?: ReactNode;
  /** Renders an open decision in place of a pending_ref block. */
  renderPending?: (pendingId: string) => ReactNode;
}) {
  const body: ReactNode[] = [];
  let chipRun: ChipBlockData[] = [];

  const flushChips = () => {
    if (!chipRun.length) return;
    const run = chipRun;
    chipRun = [];
    body.push(
      <div key={`chips-${body.length}`} className={styles.chips}>
        {run.map((block, j) => (
          <ChipBlock key={j} block={block} onOpenArtifact={onOpenArtifact} onOpenSource={onOpenSource} />
        ))}
      </div>,
    );
  };

  turn.blocks.forEach((block, i) => {
    if (isChipBlock(block)) {
      chipRun.push(block);
      return;
    }
    flushChips();
    body.push(
      <BlockView
        key={i}
        block={block}
        onOpenArtifact={onOpenArtifact}
        onOpenSource={onOpenSource}
        decisionHref={decisionHref}
        renderPending={renderPending}
      />,
    );
  });
  flushChips();

  return (
    <div className={styles.row}>
      {avatar ?? (
        <span className={styles.avatar} aria-hidden="true">
          {initials(turn.author.name)}
        </span>
      )}
      <div className={styles.body}>{body}</div>
    </div>
  );
}

function ChipBlock({
  block,
  onOpenArtifact,
  onOpenSource,
}: {
  block: ChipBlockData;
  onOpenArtifact?: (artifactId: string, version: number) => void;
  onOpenSource?: (sourceRef: string) => void;
}) {
  if ("artifact_id" in block) {
    return <ArtifactChip block={block} onOpen={onOpenArtifact} />;
  }
  return <SourceChip block={block} onOpen={onOpenSource} />;
}

function BlockView({
  block,
  onOpenArtifact,
  onOpenSource,
  decisionHref,
  renderPending,
}: {
  block: Block;
  onOpenArtifact?: (artifactId: string, version: number) => void;
  onOpenSource?: (sourceRef: string) => void;
  decisionHref?: (decisionId: string) => string | undefined;
  renderPending?: (pendingId: string) => ReactNode;
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
      return <ArtifactChip block={block} onOpen={onOpenArtifact} />;
    case "source_chip":
      return <SourceChip block={block} onOpen={onOpenSource} />;
    case "pending_ref":
      return <>{renderPending?.(block.pending_id) ?? null}</>;
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
