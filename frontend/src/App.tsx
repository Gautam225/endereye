import { MutationCache, QueryCache, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MotionConfig } from "motion/react";
import type { ReactElement } from "react";
import { createBrowserRouter, Outlet, RouterProvider } from "react-router";

import { AppShell } from "./components/AppShell";
import { AccountPage } from "./features/account/AccountPage";
import { HomeRedirect, RequireAuth, RequireRole } from "./features/auth/guards";
import { ForgotPage, InvitePage, ResetPage } from "./features/auth/LinkPages";
import { LoginPage } from "./features/auth/LoginPage";
import { SetupPage } from "./features/auth/SetupPage";
import { SharedChatPage } from "./features/chat/SharedChatPage";
import { ChatHome } from "./features/chat/ChatHome";
import { ChatPage } from "./features/chat/ChatPage";
import { ConnectionsPage } from "./features/connections/ConnectionsPage";
import { AlertsPage } from "./features/dashboards/AlertsPage";
import { DashboardsPage } from "./features/dashboards/DashboardsPage";
import { ReportsPage } from "./features/dashboards/ReportsPage";
import { SpaceRedirect } from "./features/dashboards/SpaceTabs";
import {
  toastMutationError,
  toastServerBack,
  toastServerDown,
} from "./features/notifications/globalToasts";
import { ToastViewport } from "./features/notifications/ToastViewport";
import { useConnectionToasts } from "./features/notifications/useConnectionToasts";
import { MailPage } from "./features/mail/MailPage";
import { MonitoringPage } from "./features/monitoring/MonitoringPage";
import { SpacePage } from "./features/spaces/SpacePage";
import { SpacesPage } from "./features/spaces/SpacesPage";
import { StatusPage } from "./features/status/StatusPage";
import { UsersPage } from "./features/users/UsersPage";
import { AuthProvider } from "./lib/auth";
import { ThemeProvider } from "./lib/theme";
import { NotFoundPage } from "./pages/NotFoundPage";

/** Every page, signed in or not: the pop-ups live here so they show on the sign-in page too. */
function Root() {
  useConnectionToasts();
  return (
    <>
      <Outlet />
      <ToastViewport />
    </>
  );
}

const adminOnly = (page: ReactElement) => <RequireRole roles={["admin"]}>{page}</RequireRole>;

const router = createBrowserRouter([
  {
    element: <Root />,
    children: [
      { path: "/login", element: <LoginPage /> },
      { path: "/setup", element: <SetupPage /> },
      { path: "/invite/:token", element: <InvitePage /> },
      { path: "/forgot", element: <ForgotPage /> },
      { path: "/reset/:token", element: <ResetPage /> },
      {
        element: (
          <RequireAuth>
            <AppShell />
          </RequireAuth>
        ),
        children: [
          { index: true, element: <HomeRedirect /> },
          { path: "chat", element: <ChatHome /> },
          { path: "spaces/:spaceId/chat/:conversationId?", element: <ChatPage /> },
          { path: "shared/:conversationId", element: <SharedChatPage /> },
          { path: "dashboards", element: <SpaceRedirect section="dashboards" /> },
          { path: "reports", element: <SpaceRedirect section="reports" /> },
          { path: "alerts", element: <SpaceRedirect section="alerts" /> },
          { path: "spaces/:spaceId/alerts", element: <AlertsPage /> },
          { path: "spaces/:spaceId/dashboards", element: <DashboardsPage /> },
          { path: "spaces/:spaceId/reports", element: <ReportsPage /> },
          { path: "spaces", element: <SpacesPage /> },
          { path: "spaces/:spaceId", element: <SpacePage /> },
          { path: "status", element: adminOnly(<StatusPage />) },
          { path: "monitoring", element: adminOnly(<MonitoringPage />) },
          { path: "connections", element: adminOnly(<ConnectionsPage />) },
          { path: "email", element: <MailPage /> },
          { path: "users", element: adminOnly(<UsersPage />) },
          { path: "account", element: <AccountPage /> },
          { path: "*", element: <NotFoundPage /> },
        ],
      },
    ],
  },
]);

const queryClient = new QueryClient({
  queryCache: new QueryCache({ onError: toastServerDown, onSuccess: toastServerBack }),
  mutationCache: new MutationCache({
    onError: (error, _variables, _context, mutation) => toastMutationError(error, mutation.meta),
  }),
  defaultOptions: {
    queries: {
      retry: 1,
      // What was fetched a moment ago is shown as it is, with no new request, when you come back
      // to a page or switch tabs. A change you make refreshes what it touches (each action
      // names its own queries), and anything that must stay live (running reports, the
      // notifications) polls on its own schedule. After a minute, opening a page asks again.
      staleTime: 60_000,
    },
  },
});

export function App() {
  return (
    <ThemeProvider>
      <QueryClientProvider client={queryClient}>
        <AuthProvider>
          {/* Respect the operating system's "reduce motion" setting. */}
          <MotionConfig reducedMotion="user">
            <RouterProvider router={router} />
          </MotionConfig>
        </AuthProvider>
      </QueryClientProvider>
    </ThemeProvider>
  );
}
