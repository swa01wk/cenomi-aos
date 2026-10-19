import { useQuery, useQueryClient } from "@tanstack/react-query";
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
import { useLocation, useNavigate } from "react-router";
import { client, setUnauthorizedHandler } from "../api/client";
import { clearToken, getToken, saveToken } from "../api/session";
import type { components } from "../api/schema";
import { SessionDialog } from "../components";

export type Me = components["schemas"]["Me"];

type SessionContextValue = {
  me: Me | null;
  hasToken: boolean;
  booting: boolean;
  sessionError: Error | null;
  sessionExpired: boolean;
  retrySession: () => void;
  signInWithToken: (token: string) => void;
  signOut: () => void;
  signInAgain: () => void;
  /** True while redirecting after deliberate sign-out or 401; guards must not save `from`. */
  sessionJustEnded: () => boolean;
  acknowledgeSessionEnded: () => void;
};

const SessionContext = createContext<SessionContextValue | null>(null);

export function SessionProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const location = useLocation();
  const [tokenTick, setTokenTick] = useState(0);
  const [sessionExpired, setSessionExpired] = useState(false);
  const sessionEndedRef = useRef(false);
  const hadMeRef = useRef(false);
  const cachedMeRef = useRef<Me | null>(null);
  const hasToken = useMemo(() => !!getToken(), [tokenTick]);

  const bumpToken = useCallback(() => setTokenTick((t) => t + 1), []);

  const endSession = useCallback(() => {
    sessionEndedRef.current = true;
    navigate("/", { replace: true, state: { signedOut: true } });
    clearToken();
    bumpToken();
    setSessionExpired(false);
    queryClient.removeQueries({ queryKey: ["me"] });
  }, [bumpToken, navigate, queryClient]);

  const signOut = useCallback(() => {
    endSession();
  }, [endSession]);

  const signInAgain = useCallback(() => {
    const from = location.pathname + location.search;
    sessionEndedRef.current = false;
    clearToken();
    bumpToken();
    setSessionExpired(false);
    queryClient.removeQueries({ queryKey: ["me"] });
    navigate("/", { replace: true, state: { from } });
  }, [bumpToken, location.pathname, location.search, navigate, queryClient]);

  const sessionJustEnded = useCallback(() => sessionEndedRef.current, []);
  const acknowledgeSessionEnded = useCallback(() => {
    sessionEndedRef.current = false;
  }, []);

  const meQuery = useQuery({
    queryKey: ["me"],
    enabled: hasToken && !sessionExpired,
    queryFn: async () => {
      const { data, error } = await client.GET("/me");
      if (error) throw error;
      return data!;
    },
  });

  useEffect(() => {
    if (meQuery.data) {
      hadMeRef.current = true;
      cachedMeRef.current = meQuery.data;
    }
  }, [meQuery.data]);

  useEffect(() => {
    setUnauthorizedHandler(() => {
      if (!hadMeRef.current && (meQuery.isLoading || !meQuery.data)) {
        endSession();
        return;
      }
      clearToken();
      bumpToken();
      setSessionExpired(true);
    });
    return () => setUnauthorizedHandler(() => {});
  }, [bumpToken, endSession, meQuery.data, meQuery.isLoading]);

  const signInWithToken = useCallback(
    (token: string) => {
      sessionEndedRef.current = false;
      setSessionExpired(false);
      saveToken(token);
      bumpToken();
      queryClient.removeQueries({ queryKey: ["me"] });
      void queryClient.invalidateQueries({ queryKey: ["me"] });
    },
    [bumpToken, queryClient],
  );

  const retrySession = useCallback(() => {
    void meQuery.refetch();
  }, [meQuery]);

  const booting = hasToken && !sessionExpired && meQuery.isLoading;

  const sessionError =
    hasToken && !sessionExpired && meQuery.isError
      ? meQuery.error instanceof Error
        ? meQuery.error
        : new Error(String(meQuery.error))
      : null;

  const value = useMemo(
    (): SessionContextValue => ({
      me:
        sessionExpired && cachedMeRef.current
          ? cachedMeRef.current
          : hasToken && meQuery.data
            ? meQuery.data
            : null,
      hasToken,
      booting,
      sessionError,
      sessionExpired,
      retrySession,
      signInWithToken,
      signOut,
      signInAgain,
      sessionJustEnded,
      acknowledgeSessionEnded,
    }),
    [
      acknowledgeSessionEnded,
      booting,
      hasToken,
      meQuery.data,
      retrySession,
      sessionError,
      sessionExpired,
      sessionJustEnded,
      signInAgain,
      signInWithToken,
      signOut,
    ],
  );

  return (
    <SessionContext.Provider value={value}>
      {children}
      <SessionDialog open={sessionExpired} onSignIn={signInAgain} />
    </SessionContext.Provider>
  );
}

export function useSession(): SessionContextValue {
  const ctx = useContext(SessionContext);
  if (!ctx) throw new Error("useSession outside SessionProvider");
  return ctx;
}
