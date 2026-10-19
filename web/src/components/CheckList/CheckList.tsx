import styles from "./CheckList.module.css";

export type CheckListItem = {
  name: string;
  status: "pass" | "fail" | "pending";
  detail?: string;
};

export function CheckList({ items }: { items: CheckListItem[] }) {
  return (
    <ul className={styles.list}>
      {items.map((item) => (
        <li key={item.name} className={styles.row}>
          <div className={styles.head}>
            <span className={`${styles.status} ${styles[item.status]}`}>{item.status}</span>
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
