import { Navigate, Outlet, useLocation } from "react-router";
import { ErrorBanner, Skeleton } from "../components";
import { useSession } from "./session";

function savedFromPath(location: ReturnType<typeof useLocation>): string {
  return location.pathname + location.search;
}

function signInRedirectState(
  location: ReturnType<typeof useLocation>,
  sessionJustEnded: () => boolean,
): { from: string } | { signedOut: true } {
  if (sessionJustEnded()) return { signedOut: true };
  return { from: savedFromPath(location) };
}

export function RequireAuth() {
  const { me, booting, sessionError, retrySession, sessionJustEnded, sessionExpired } = useSession();
  const location = useLocation();

  if (sessionError) {
    return (
      <main style={{ padding: 40, display: "flex", flexDirection: "column", gap: 12 }}>
        <ErrorBanner title={`Can't load your session`} detail={sessionError.message} onRetry={retrySession} />
      </main>
    );
  }

  if (booting) {
    return (
      <main style={{ padding: 40 }}>
        <Skeleton />
      </main>
    );
  }
  if (!me && !sessionExpired) {
    if (sessionJustEnded()) return null;
    return <Navigate to="/" replace state={signInRedirectState(location, sessionJustEnded)} />;
  }
  return <Outlet context={me} />;
}

export function RequireConsole() {
  const { me, booting, sessionError, retrySession, sessionJustEnded } = useSession();
  const location = useLocation();

  if (sessionError) {
    return (
      <main style={{ padding: 40, display: "flex", flexDirection: "column", gap: 12 }}>
        <ErrorBanner title={`Can't load your session`} detail={sessionError.message} onRetry={retrySession} />
      </main>
    );
  }

  if (booting) {
    return (
      <main style={{ padding: 40 }}>
        <Skeleton />
      </main>
    );
  }
  if (!me) {
    if (sessionJustEnded()) return null;
    return <Navigate to="/" replace state={signInRedirectState(location, sessionJustEnded)} />;
  }
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
