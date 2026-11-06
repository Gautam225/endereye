import { useQueryClient } from "@tanstack/react-query";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import {
  ApiError,
  apiSend,
  publicSend,
  refreshSession,
  setAccessToken,
  setSessionLostHandler,
  type Role,
  type Session,
  type User,
} from "./api";
import { toast } from "./toast";

export type AuthState =
  | { status: "loading" }
  | { status: "setup" } // no accounts yet: create the first admin
  | { status: "anonymous"; reason?: "expired" | "signed_out" }
  | { status: "authenticated"; user: User }
  | { status: "error"; error: ApiError }; // backend or database not ready

interface AuthContextValue {
  state: AuthState;
  user: User | null;
  hasRole: (...roles: Role[]) => boolean;
  login: (email: string, password: string) => Promise<void>;
  setup: (input: { full_name: string; email: string; password: string }) => Promise<void>;
  /** Join with an invitation link: choose a name and password, and be signed in. */
  acceptInvite: (token: string, fullName: string, password: string) => Promise<void>;
  /** Choose a new password with a reset link, and be signed in. */
  resetPassword: (token: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  changePassword: (currentPassword: string, newPassword: string) => Promise<void>;
  /** Check the backend again (used by the startup error screen). */
  retry: () => void;
  checking: boolean;
}

const AuthContext = createContext<AuthContextValue | null>(null);

function asApiError(error: unknown): ApiError {
  return error instanceof ApiError
    ? error
    : new ApiError("Something went wrong.", { code: "error", status: 0 });
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const [state, setState] = useState<AuthState>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);
  const [checking, setChecking] = useState(false);
  const checkingRef = useRef(false);

  const startSession = useCallback((session: Session) => {
    setAccessToken(session.access_token);
    setState({ status: "authenticated", user: session.user });
  }, []);

  const endSession = useCallback(
    (reason: "expired" | "signed_out") => {
      setAccessToken(null);
      queryClient.clear(); // no data from the previous user stays in memory
      setState({ status: "anonymous", reason });
    },
    [queryClient],
  );

  // On load (and on retry): first-run setup? Otherwise resume the session from the cookie.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const { needs_setup } = await publicSend<{ needs_setup: boolean }>("GET", "/auth/setup");
        if (cancelled) return;
        if (needs_setup) {
          setState({ status: "setup" });
          return;
        }
        const session = await refreshSession();
        if (cancelled) return;
        if (session) startSession(session);
        else setState({ status: "anonymous" });
      } catch (error) {
        if (!cancelled) setState({ status: "error", error: asApiError(error) });
      } finally {
        checkingRef.current = false;
        if (!cancelled) setChecking(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [attempt, startSession]);

  useEffect(() => {
    setSessionLostHandler(() => {
      endSession("expired");
      toast.warning("You were signed out", {
        id: "signed-out",
        body: "Your session ended. Sign in again to carry on.",
        link: "/login",
        duration: 12_000,
      });
    });
    return () => setSessionLostHandler(null);
  }, [endSession]);

  // Stable, and ignored while a check is already running, so it is safe to call on a timer.
  const retry = useCallback(() => {
    if (checkingRef.current) return;
    checkingRef.current = true;
    setChecking(true);
    setAttempt((n) => n + 1);
  }, []);

  const value = useMemo<AuthContextValue>(() => {
    const user = state.status === "authenticated" ? state.user : null;
    return {
      state,
      user,
      hasRole: (...roles) => (user ? roles.includes(user.role) : false),
      login: async (email, password) => {
        startSession(await publicSend<Session>("POST", "/auth/login", { email, password }));
      },
      setup: async (input) => {
        startSession(await publicSend<Session>("POST", "/auth/setup", input));
      },
      acceptInvite: async (token, fullName, password) => {
        startSession(
          await publicSend<Session>("POST", "/auth/invite/accept", {
            token,
            full_name: fullName,
            password,
          }),
        );
      },
      resetPassword: async (token, password) => {
        startSession(await publicSend<Session>("POST", "/auth/reset", { token, password }));
      },
      logout: async () => {
        try {
          await publicSend("POST", "/auth/logout");
        } finally {
          endSession("signed_out");
        }
      },
      changePassword: async (currentPassword, newPassword) => {
        startSession(
          await apiSend<Session>("POST", "/auth/password", {
            current_password: currentPassword,
            new_password: newPassword,
          }),
        );
      },
      retry,
      checking,
    };
  }, [state, startSession, endSession, retry, checking]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

// eslint-disable-next-line react-refresh/only-export-components
export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth must be used inside <AuthProvider>");
  return value;
}
