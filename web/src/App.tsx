import { useCallback, useEffect, useState } from "react";
import { type Session, loadSession, saveSession, setToken } from "./api";
import Login from "./Login";
import ConsoleApp from "./console/ConsoleApp";
import Workspace from "./workspace/Workspace";

/** Hash routes keep the POC free of a router dependency: #/console/packs, #/workspace, … */
export function useRoute(): [string[], (to: string) => void] {
  const read = () => window.location.hash.replace(/^#\/?/, "").split("/").filter(Boolean);
  const [parts, setParts] = useState<string[]>(read);
  useEffect(() => {
    const on = () => setParts(read());
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  const go = useCallback((to: string) => {
    window.location.hash = to;
  }, []);
  return [parts, go];
}

export default function App() {
  const [session, setSession] = useState<Session | null>(loadSession);
  const [route, go] = useRoute();

  const signOut = useCallback(() => {
    saveSession(null);
    setToken(null);
    setSession(null);
    go("/");
  }, [go]);

  useEffect(() => setToken(session?.token ?? null, signOut), [session, signOut]);

  const signIn = (s: Session) => {
    saveSession(s);
    setToken(s.token, signOut);
    setSession(s);
    go(s.person.console ? "/console/packs" : "/workspace");
  };

  if (!session) return <Login onSignedIn={signIn} />;

  if (route[0] === "console" && session.person.console) {
    return <ConsoleApp session={session} route={route.slice(1)} signOut={signOut} />;
  }
  return <Workspace session={session} signOut={signOut} />;
}
