import styles from "./FieldError.module.css";

export function FieldError({ id, message }: { id: string; message: string }) {
  return (
    <span id={id} className={styles.error} role="alert">
      {message}
    </span>
  );
}
