import { Link } from "react-router";
import styles from "./RefusalNotice.module.css";

export function RefusalNotice({
  title,
  detail,
  rule,
  decisionId,
  decisionHref,
}: {
  title: string;
  detail?: string;
  rule?: string;
  decisionId?: string;
  decisionHref?: string;
}) {
  return (
    <div role="note" className={styles.notice}>
      <svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="#4A5160" strokeWidth="1.6" aria-hidden="true">
        <rect x="3.5" y="8" width="11" height="7" rx="1.5" />
        <path d="M6 8V6a3 3 0 016 0v2" />
      </svg>
      <div className={styles.body}>
        <p className={styles.title}>{title}</p>
        {detail && <p className={styles.detail}>{detail}</p>}
        {(rule || decisionId) && (
          <p className={styles.meta}>
            {rule && <>rule {rule}</>}
            {rule && decisionId && " · "}
            {decisionId && (
              <>
                decision{" "}
                {decisionHref ? (
                  <Link to={decisionHref} className={styles.link}>
                    {decisionId}
                  </Link>
                ) : (
                  decisionId
                )}
              </>
            )}
          </p>
        )}
      </div>
    </div>
  );
}
