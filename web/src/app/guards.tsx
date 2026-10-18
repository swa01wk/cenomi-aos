import { Navigate, Outlet, useLocation } from "react-router";
import { Loading } from "../lib/ui";
import { useSession } from "./session";

export function RequireAuth() {
  const { me, booting } = useSession();
  const location = useLocation();
  const hasToken = typeof localStorage !== "undefined" && !!localStorage.getItem("aos.token");

  if (booting || (hasToken && !me)) {
    return <Loading what="your session" />;
  }
  if (!me) {
    return <Navigate to="/" replace state={{ from: location.pathname + location.search }} />;
  }
  return <Outlet context={me} />;
}

export function RequireConsole() {
  const { me, booting } = useSession();
  const location = useLocation();

  if (booting) return <Loading what="your session" />;
  if (!me) return <Navigate to="/" replace state={{ from: location.pathname }} />;
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
