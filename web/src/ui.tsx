import { useCallback, useEffect, useState } from "react";

export function initials(name: string): string {
  const words = name.split(/\s+/).filter(Boolean);
  const capitalised = words.filter((w) => /^[A-Z]/.test(w));
  return (capitalised.length >= 2 ? capitalised : words)
    .slice(0, 2)
    .map((w) => w[0]!.toUpperCase())
    .join("");
}

export function shortHash(h: string, n = 10): string {
  return h.slice(0, n);
}

export function when(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

export function teamLabel(team: string): string {
  const [dept, t] = team.split("/");
  const cap = (s = "") => s.charAt(0).toUpperCase() + s.slice(1);
  return dept === t ? cap(dept) : `${cap(dept)} · ${cap(t)}`;
}

const STATUS_TONE: Record<string, string> = {
  validated: "ok",
  published: "info",
  invalid: "bad",
  draft: "",
  publish_requested: "warn",
  retired: "",
};

export function StatusPill({ status }: { status: string }) {
  return <span className={`pill ${STATUS_TONE[status] ?? ""}`}>{status.replace("_", " ")}</span>;
}

/** Load once on mount (and on `reload()`), exposing data, error and loading. */
export function useLoad<T>(load: () => Promise<T>, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const run = useCallback(load, deps);
  const reload = useCallback(() => {
    setLoading(true);
    run()
      .then((d) => {
        setData(d);
        setError(null);
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }, [run]);
  useEffect(reload, [reload]);
  return { data, error, loading, reload };
}

export function Loading({ what }: { what: string }) {
  return <p className="muted">Loading {what}…</p>;
}

export function ErrorNote({ message }: { message: string }) {
  return (
    <div className="banner bad" role="alert">
      {message}
    </div>
  );
}
