import styles from "./CheckList.module.css";

export type CheckListItem = {
  name: string;
  status: "pass" | "fail" | "pending";
  detail?: string;
};

function StatusIcon({ status }: { status: CheckListItem["status"] }) {
  const iconClass =
    status === "pass" ? styles.iconPass : status === "fail" ? styles.iconFail : styles.iconPending;

  if (status === "pass") {
    return (
      <svg className={`${styles.icon} ${iconClass}`} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
        <path d="M3 8.5l3 3 7-7" />
      </svg>
    );
  }
  if (status === "fail") {
    return (
      <svg className={`${styles.icon} ${iconClass}`} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
        <path d="M4 4l8 8M12 4l-8 8" />
      </svg>
    );
  }
  return (
    <svg className={`${styles.icon} ${iconClass}`} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4" aria-hidden="true">
      <circle cx="8" cy="8" r="5.5" />
    </svg>
  );
}

export function CheckList({ items }: { items: CheckListItem[] }) {
  return (
    <ul className={styles.list}>
      {items.map((item) => (
        <li key={item.name} className={styles.row}>
          <div className={styles.head}>
            <StatusIcon status={item.status} />
            <span className={styles.srOnly}>{item.status}</span>
            <span>{item.name}</span>
          </div>
          {item.detail && <p className={styles.detail}>{item.detail}</p>}
        </li>
      ))}
    </ul>
  );
}

export function checksFromSeatDetail(checks: { name: string; passed: boolean; detail?: string }[]): CheckListItem[] {
  return checks.map((c) => ({
    name: c.name,
    status: c.passed ? "pass" : "fail",
    detail: c.detail,
  }));
}
