import styles from "./SeatNotice.module.css";

export function SeatNotice({
  title,
  detail,
}: {
  code: "seat_not_active" | "kill_switch_active";
  title: string;
  detail?: string;
}) {
  return (
    <div role="status" className={styles.banner}>
      <p className={styles.title}>{title}</p>
      {detail && <p className={styles.detail}>{detail}</p>}
    </div>
  );
}
