import { useQuery, useQueryClient } from "@tanstack/react-query";
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { useNavigate } from "react-router";
import { client, setUnauthorizedHandler } from "../api/client";
import { clearToken, getToken, saveToken } from "../api/session";
import type { components } from "../api/schema";

export type Me = components["schemas"]["Me"];

type SessionContextValue = {
  me: Me | null;
  hasToken: boolean;
  booting: boolean;
  sessionError: Error | null;
  retrySession: () => void;
  signInWithToken: (token: string) => void;
  signOut: () => void;
};

const SessionContext = createContext<SessionContextValue | null>(null);

export function SessionProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [tokenTick, setTokenTick] = useState(0);
  const hasToken = useMemo(() => !!getToken(), [tokenTick]);

  const bumpToken = useCallback(() => setTokenTick((t) => t + 1), []);

  const signOut = useCallback(() => {
    clearToken();
    bumpToken();
    queryClient.removeQueries({ queryKey: ["me"] });
    navigate("/", { replace: true });
  }, [bumpToken, navigate, queryClient]);

  useEffect(() => {
    setUnauthorizedHandler(() => {
      bumpToken();
      queryClient.removeQueries({ queryKey: ["me"] });
      navigate("/", { replace: true });
    });
    return () => setUnauthorizedHandler(() => {});
  }, [bumpToken, navigate, queryClient]);

  const meQuery = useQuery({
    queryKey: ["me"],
    enabled: hasToken,
    queryFn: async () => {
      const { data, error } = await client.GET("/me");
      if (error) throw error;
      return data!;
    },
  });

  const signInWithToken = useCallback(
    (token: string) => {
      saveToken(token);
      bumpToken();
      queryClient.invalidateQueries({ queryKey: ["me"] });
    },
    [bumpToken, queryClient],
  );

  const retrySession = useCallback(() => {
    void meQuery.refetch();
  }, [meQuery]);

  const booting = hasToken && meQuery.isLoading;

  const sessionError =
    hasToken && meQuery.isError ? (meQuery.error instanceof Error ? meQuery.error : new Error(String(meQuery.error))) : null;

  const value = useMemo(
    (): SessionContextValue => ({
      me: hasToken && meQuery.data ? meQuery.data : null,
      hasToken,
      booting,
      sessionError,
      retrySession,
      signInWithToken,
      signOut,
    }),
    [booting, hasToken, meQuery.data, retrySession, sessionError, signInWithToken, signOut],
  );

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): SessionContextValue {
  const ctx = useContext(SessionContext);
  if (!ctx) throw new Error("useSession outside SessionProvider");
  return ctx;
}
