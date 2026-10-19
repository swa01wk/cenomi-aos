import type { Problem } from "../../api/problems";
import { ConflictNotice } from "../ConflictNotice/ConflictNotice";
import { ErrorBanner } from "../ErrorBanner/ErrorBanner";
import { FieldError } from "../FieldError/FieldError";
import { problemNotice } from "../problemNotice";
import { RefusalNotice } from "../RefusalNotice/RefusalNotice";
import { SeatNotice } from "../SeatNotice/SeatNotice";
import { SessionDialog } from "../SessionDialog/SessionDialog";

export function ProblemNotice({
  problem,
  onRetry,
  onReload,
  decisionHref,
  sessionOpen = true,
  onSignIn,
}: {
  problem: Problem;
  onRetry?: () => void;
  onReload?: () => void;
  decisionHref?: string;
  sessionOpen?: boolean;
  onSignIn?: () => void;
}) {
  const d = problemNotice(problem);

  switch (d.kind) {
    case "session":
      return <SessionDialog open={sessionOpen} onSignIn={onSignIn ?? (() => {})} title={d.props.title} detail={d.props.detail} />;
    case "refusal":
      return (
        <RefusalNotice
          title={d.props.title}
          detail={d.props.detail}
          rule={d.props.rule}
          decisionId={d.props.decisionId}
          decisionHref={decisionHref}
        />
      );
    case "seat":
      return <SeatNotice code={d.props.code} title={d.props.title} detail={d.props.detail} />;
    case "conflict":
      return <ConflictNotice title={d.props.title} detail={d.props.detail} onReload={onReload} />;
    case "fields":
      return (
        <div>
          {d.props.fields.map((f) => (
            <FieldError key={f.name} id={`field-error-${f.name}`} message={`${f.name}: ${f.message}`} />
          ))}
        </div>
      );
    case "error":
      return (
        <ErrorBanner
          title={d.props.title}
          detail={d.props.detail}
          status={problem.status}
          traceId={d.props.traceId}
          onRetry={d.props.retryable ? onRetry : undefined}
        />
      );
  }
}
