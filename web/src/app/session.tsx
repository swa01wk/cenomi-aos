import { useQuery, useQueryClient } from "@tanstack/react-query";
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { useNavigate } from "react-router";
import { client, setUnauthorizedHandler } from "../api/client";
import { clearToken, getToken, saveToken } from "../api/session";
import type { components } from "../api/schema";

export type Me = components["schemas"]["Me"];

type SessionContextValue = {
  me: Me | null;
  booting: boolean;
  signInWithToken: (token: string) => void;
  signOut: () => void;
};

const SessionContext = createContext<SessionContextValue | null>(null);

export function SessionProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [tokenTick, setTokenTick] = useState(0);
  const hasToken = useMemo(() => !!getToken(), [tokenTick]);

  const signOut = useCallback(() => {
    clearToken();
    setTokenTick((t) => t + 1);
    queryClient.removeQueries({ queryKey: ["me"] });
    navigate("/", { replace: true });
  }, [navigate, queryClient]);

  useEffect(() => {
    setUnauthorizedHandler(() => {
      queryClient.removeQueries({ queryKey: ["me"] });
      navigate("/", { replace: true });
    });
    return () => setUnauthorizedHandler(() => {});
  }, [navigate, queryClient]);

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
      setTokenTick((t) => t + 1);
      queryClient.invalidateQueries({ queryKey: ["me"] });
    },
    [queryClient],
  );

  const booting = hasToken && meQuery.isPending;

  const value = useMemo(
    (): SessionContextValue => ({
      me: hasToken && meQuery.data ? meQuery.data : null,
      booting,
      signInWithToken,
      signOut,
    }),
    [booting, hasToken, meQuery.data, signInWithToken, signOut],
  );

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): SessionContextValue {
  const ctx = useContext(SessionContext);
  if (!ctx) throw new Error("useSession outside SessionProvider");
  return ctx;
}
