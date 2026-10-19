import type { ReactNode } from "react";
import styles from "./Panel.module.css";

export function Panel({
  title,
  label,
  children,
  header,
}: {
  title?: string;
  label?: string;
  children: ReactNode;
  header?: ReactNode;
}) {
  return (
    <section className={styles.panel} aria-label={label ?? title}>
      {(title || header) && (
        <div className={styles.head}>
          {title && <h2 className={styles.title}>{title}</h2>}
          {header}
        </div>
      )}
      <div className={styles.body}>{children}</div>
    </section>
  );
}
