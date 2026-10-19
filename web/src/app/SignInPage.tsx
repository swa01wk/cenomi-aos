import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router";
import { client } from "../api/client";
import type { components } from "../api/schema";
import { ErrorBanner, Skeleton } from "../components";
import { initials, teamLabel } from "../lib/ui";
import { postSignInPath } from "./landing";
import { useSession } from "./session";

type Person = components["schemas"]["Person"];

export default function SignInPage() {
  const { me, booting, signInWithToken, acknowledgeSessionEnded } = useSession();
  const navigate = useNavigate();
  const location = useLocation();
  const [failure, setFailure] = useState<string | null>(null);

  const { data: people, error } = useQuery({
    queryKey: ["personas"],
    queryFn: async () => {
      const { data } = await client.GET("/auth/personas");
      return data ?? [];
    },
  });

  useEffect(() => {
    acknowledgeSessionEnded();
  }, [acknowledgeSessionEnded]);

  useEffect(() => {
    if (booting || !me) return;
    const state = (location.state as { from?: string; signedOut?: boolean } | null) ?? {};
    const from = state.signedOut ? undefined : state.from;
    const target = postSignInPath(from, me.console, me.roles);
    navigate(target, { replace: true, state: null });
  }, [booting, location.state, me, navigate]);

  const signIn = useMutation({
    mutationFn: async (person_id: string) => {
      const { data } = await client.POST("/auth/session", { body: { person_id } });
      if (!data) throw new Error("No session returned");
      return data;
    },
    onSuccess: (data) => {
      setFailure(null);
      signInWithToken(data.token);
    },
    onError: (e: Error) => setFailure(e.message),
  });

  if (booting) return <Skeleton />;
  if (me) return <Skeleton />;

  const group = (console: boolean) => (people ?? []).filter((p) => p.console === console);

  return (
    <div className="login">
      <div className="login-card">
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <div className="logo">AOS</div>
          <div style={{ display: "flex", flexDirection: "column" }}>
            <h1>Sign in</h1>
            <span className="sub">POC sandbox organization</span>
          </div>
        </div>
        <div className="banner info">
          POC sign-in: pick a seeded person. Each one sees what their roles allow; single sign-on replaces this after
          the POC.
        </div>
        {error && <ErrorBanner title="Can't reach the kernel" detail={(error as Error).message} />}
        {failure && <ErrorBanner title="Sign in failed" detail={failure} />}
        {!people && !error && <Skeleton />}
        {people && (
          <>
            <Section title="Workspace" hint="Request, buy and approve work" people={group(false)} busy={signIn.isPending ? signIn.variables : null} onPick={(p) => signIn.mutate(p.id)} />
            <Section title="Console" hint="Define, govern and operate digital workers" people={group(true)} busy={signIn.isPending ? signIn.variables : null} onPick={(p) => signIn.mutate(p.id)} />
          </>
        )}
      </div>
    </div>
  );
}

function Section(props: {
  title: string;
  hint: string;
  people: Person[];
  busy: string | null | undefined;
  onPick: (p: Person) => void;
}) {
  return (
    <section aria-label={props.title} style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      <div>
        <h2>{props.title}</h2>
        <span className="muted">{props.hint}</span>
      </div>
      <div className="persona-grid">
        {props.people.map((p) => (
          <button key={p.id} type="button" className="persona" onClick={() => props.onPick(p)} disabled={!!props.busy}>
            <span className={`avatar ${p.console ? "console" : ""}`}>{initials(p.name)}</span>
            <span className="who">
              <span style={{ fontWeight: 500 }}>{props.busy === p.id ? "Signing in…" : p.name}</span>
              <span className="muted" style={{ fontSize: 12 }}>
                {teamLabel(p.team)} · {p.roles.join(", ").replace(/_/g, " ")}
              </span>
            </span>
          </button>
        ))}
      </div>
    </section>
  );
}
