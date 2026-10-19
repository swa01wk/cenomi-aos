import { Link } from "react-router";
import styles from "./StatTile.module.css";

export function StatTile({ label, value, href }: { label: string; value: string; href?: string }) {
  const body = (
    <>
      <span className={styles.label}>{label}</span>
      <span className={styles.value}>{value}</span>
    </>
  );
  if (href) {
    return (
      <Link to={href} className={styles.tile}>
        {body}
      </Link>
    );
  }
  return <div className={styles.tile}>{body}</div>;
}
