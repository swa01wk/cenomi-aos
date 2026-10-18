import { Navigate, Outlet, useLocation } from "react-router";
import { ErrorNote, Loading } from "../lib/ui";
import { useSession } from "./session";

function savedFromPath(location: ReturnType<typeof useLocation>): string {
  return location.pathname + location.search;
}

export function RequireAuth() {
  const { me, booting, sessionError, retrySession } = useSession();
  const location = useLocation();

  if (sessionError) {
    return (
      <main style={{ padding: 40, display: "flex", flexDirection: "column", gap: 12 }}>
        <ErrorNote message={`Can't load your session: ${sessionError.message}`} />
        <button type="button" className="btn primary" onClick={retrySession}>
          Retry
        </button>
      </main>
    );
  }

  if (booting) {
    return <Loading what="your session" />;
  }
  if (!me) {
    return <Navigate to="/" replace state={{ from: savedFromPath(location) }} />;
  }
  return <Outlet context={me} />;
}

export function RequireConsole() {
  const { me, booting, sessionError, retrySession } = useSession();
  const location = useLocation();

  if (sessionError) {
    return (
      <main style={{ padding: 40, display: "flex", flexDirection: "column", gap: 12 }}>
        <ErrorNote message={`Can't load your session: ${sessionError.message}`} />
        <button type="button" className="btn primary" onClick={retrySession}>
          Retry
        </button>
      </main>
    );
  }

  if (booting) return <Loading what="your session" />;
  if (!me) return <Navigate to="/" replace state={{ from: savedFromPath(location) }} />;
  if (!me.console) {
    return (
      <main style={{ padding: 40 }}>
        <h1>Console not available</h1>
        <p className="sub">Your account does not include Console access. The kernel returns 403 if you call Console APIs.</p>
      </main>
    );
  }
  return <Outlet />;
}
