import { Outlet, useLocation } from "react-router";
import { ShellProvider } from "../components";
import { useRefetchWorkspaceOnFocus } from "./useWorkspaceQueries";
import { WorkspaceRail } from "./WorkspaceRail";

export default function WorkspaceShell() {
  useRefetchWorkspaceOnFocus();
  const location = useLocation();
  const flushMain = /^\/workspace\/jobs\//.test(location.pathname);

  return (
    <ShellProvider shell="workspace">
      <div className="shell">
        <WorkspaceRail />
        <main className={flushMain ? "ws-main ws-main-flush" : "ws-main"}>
          <Outlet />
        </main>
      </div>
    </ShellProvider>
  );
}
