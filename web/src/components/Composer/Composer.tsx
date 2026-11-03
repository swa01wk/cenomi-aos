import { useEffect, useRef, useState, type KeyboardEvent, type RefObject } from "react";
import { Button } from "../Button/Button";
import { newClientTurnId } from "../clientTurnId";
import styles from "./Composer.module.css";

export function Composer({
  onSend,
  disabledReason,
  initialText = "",
  onTextChange,
  agentBusy = false,
  expanded = false,
  focusToken = 0,
  placeholder = "Message",
  inputRef,
}: {
  onSend: (text: string, clientTurnId: string) => Promise<void>;
  disabledReason?: string;
  initialText?: string;
  onTextChange?: (text: string) => void;
  agentBusy?: boolean;
  /** Taller input for answering several questions at once. */
  expanded?: boolean;
  /** Increment to move focus into the input (e.g. after Reply on a message). */
  focusToken?: number;
  placeholder?: string;
  inputRef?: RefObject<HTMLTextAreaElement | null>;
}) {
  const [text, setText] = useState(initialText);
  const [sending, setSending] = useState(false);
  const clientTurnIdRef = useRef<string | null>(null);
  const lastSentTextRef = useRef("");
  const localInputRef = useRef<HTMLTextAreaElement>(null);
  const areaRef = inputRef ?? localInputRef;

  useEffect(() => {
    setText(initialText);
  }, [initialText]);

  useEffect(() => {
    if (text !== lastSentTextRef.current) {
      clientTurnIdRef.current = null;
    }
  }, [text]);

  useEffect(() => {
    if (focusToken <= 0) return;
    const el = areaRef.current;
    if (!el || disabledReason) return;
    el.focus();
    const len = el.value.length;
    el.setSelectionRange(len, len);
  }, [focusToken, disabledReason, areaRef]);

  const setTextAndNotify = (next: string) => {
    setText(next);
    onTextChange?.(next);
  };

  const send = async () => {
    const trimmed = text.trim();
    if (!trimmed || disabledReason || sending) return;
    if (!clientTurnIdRef.current) {
      clientTurnIdRef.current = newClientTurnId();
    }
    const id = clientTurnIdRef.current;
    setSending(true);
    try {
      await onSend(trimmed, id);
      lastSentTextRef.current = "";
      clientTurnIdRef.current = null;
      setTextAndNotify("");
    } catch {
      lastSentTextRef.current = text;
    } finally {
      setSending(false);
    }
  };

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void send();
    }
  };

  const blocked = Boolean(disabledReason);

  return (
    <div className={styles.root}>
      <textarea
        ref={areaRef}
        className={expanded ? `${styles.input} ${styles.inputExpanded}` : styles.input}
        value={text}
        onChange={(e) => setTextAndNotify(e.target.value)}
        onKeyDown={onKeyDown}
        aria-disabled={blocked ? "true" : undefined}
        readOnly={blocked}
        rows={expanded ? 5 : 1}
        aria-label="Message"
        placeholder={placeholder}
      />
      {agentBusy ? (
        <Button
          variant="secondary"
          disabledReason="Stop is not available in this preview. Leave the page if you do not want to wait; the worker continues until this step finishes."
          aria-label="Stop"
        >
          Stop
        </Button>
      ) : null}
      <Button
        variant="dark"
        iconOnly
        aria-label="Send"
        disabledReason={disabledReason ?? (agentBusy ? "Wait for the current reply to finish" : undefined)}
        aria-busy={sending || undefined}
        onClick={() => void send()}
      >
        <svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true">
          <path d="M9 15V3M4 8l5-5 5 5" />
        </svg>
      </Button>
    </div>
  );
}
