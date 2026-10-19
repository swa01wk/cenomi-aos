import { useEffect, useRef } from "react";
import { Button } from "../Button/Button";
import styles from "./SessionDialog.module.css";

export function SessionDialog({
  open,
  onSignIn,
  title = "Your session has ended",
  detail = "Sign in again to carry on. Anything you were typing is kept.",
}: {
  open: boolean;
  onSignIn: () => void;
  title?: string;
  detail?: string;
}) {
  const signInRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (open) signInRef.current?.focus();
  }, [open]);

  if (!open) return null;

  return (
    <div className={styles.backdrop}>
      <div role="dialog" aria-modal="true" aria-labelledby="session-dialog-title" className={styles.dialog}>
        <p id="session-dialog-title" className={styles.title}>
          {title}
        </p>
        <p className={styles.detail}>{detail}</p>
        <Button ref={signInRef} variant="dark" onClick={onSignIn}>
          Sign in
        </Button>
      </div>
    </div>
  );
}
