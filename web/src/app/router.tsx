import { createBrowserRouter, Outlet } from "react-router";
import AuditPage from "../console/AuditPage";
import ConsoleShell from "../console/ConsoleShell";
import OrgPage from "../console/OrgPage";
import PacksPage from "../console/PacksPage";
import VersionPage from "../console/VersionPage";
import WorkspaceShell from "../workspace/WorkspaceShell";
import { AppErrorBoundary } from "./AppErrorBoundary";
import HashRedirect from "./HashRedirect";
import { RequireAuth, RequireConsole } from "./guards";
import SignInPage from "./SignInPage";
import { SessionProvider } from "./session";

function RootLayout() {
  return (
    <AppErrorBoundary>
      <SessionProvider>
        <HashRedirect />
        <Outlet />
      </SessionProvider>
    </AppErrorBoundary>
  );
}

const devRoutes = import.meta.env.DEV
  ? [
      {
        path: "/dev/components",
        lazy: async () => {
          const { default: ComponentsGalleryPage } = await import("../dev/ComponentsGalleryPage");
          return { Component: ComponentsGalleryPage };
        },
      },
    ]
  : [];

export const router = createBrowserRouter([
  {
    element: <RootLayout />,
    children: [
      { path: "/", element: <SignInPage /> },
      ...devRoutes,
      {
        element: <RequireAuth />,
        children: [
          { path: "/workspace", element: <WorkspaceShell /> },
          {
            element: <RequireConsole />,
            children: [
              {
                element: <ConsoleShell />,
                children: [
                  { path: "/console/org", element: <OrgPage /> },
                  { path: "/console/packs", element: <PacksPage /> },
                  { path: "/console/versions/:id", element: <VersionPage /> },
                  { path: "/console/audit", element: <AuditPage /> },
                ],
              },
            ],
          },
        ],
      },
    ],
  },
]);
