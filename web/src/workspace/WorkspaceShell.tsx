import { Outlet, useLocation } from "react-router";
import { ShellProvider } from "../components";
import { useRefetchWorkspaceOnFocus } from "./useWorkspaceQueries";
import { WorkspaceRail } from "./WorkspaceRail";

export default function WorkspaceShell() {
  useRefetchWorkspaceOnFocus();
  const location = useLocation();
  const flushMain = /^\/workspace\/(jobs\/|new$)/.test(location.pathname);

  return (
    <ShellProvider shell="workspace">
      <div className="shell ws-theme">
        <WorkspaceRail />
        <main className={flushMain ? "ws-main ws-main-flush" : "ws-main"}>
          <Outlet />
        </main>
      </div>
    </ShellProvider>
  );
}
