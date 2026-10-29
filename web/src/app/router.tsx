import { createBrowserRouter, Outlet } from "react-router";
import AuditPage from "../console/AuditPage";
import ConsoleShell from "../console/ConsoleShell";
import OrgPage from "../console/OrgPage";
import PacksPage from "../console/PacksPage";
import SeatPage from "../console/SeatPage";
import SeatsPage from "../console/SeatsPage";
import VersionPage from "../console/VersionPage";
import JobPage from "../workspace/job/JobPage";
import MyJobsPage from "../workspace/MyJobsPage";
import QueuePage from "../workspace/QueuePage";
import ChatHomePage from "../workspace/ChatHomePage";
import EmployeeHubPage from "../workspace/EmployeeHubPage";
import PersonChatPage from "../workspace/PersonChatPage";
import NewJobPage from "../workspace/NewJobPage";
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
          {
            path: "/workspace",
            element: <WorkspaceShell />,
            children: [
              { index: true, element: <ChatHomePage /> },
              { path: "jobs", element: <MyJobsPage /> },
              { path: "queue", element: <QueuePage /> },
              { path: "people/:seat", element: <EmployeeHubPage /> },
              { path: "people/:seat/:instanceId", element: <PersonChatPage /> },
              { path: "new", element: <NewJobPage /> },
              { path: "jobs/:id", element: <JobPage /> },
            ],
          },
          {
            element: <RequireConsole />,
            children: [
              {
                element: <ConsoleShell />,
                children: [
                  { path: "/console/org", element: <OrgPage /> },
                  { path: "/console/packs", element: <PacksPage /> },
                  { path: "/console/seats", element: <SeatsPage /> },
                  { path: "/console/seats/:seat", element: <SeatPage /> },
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
