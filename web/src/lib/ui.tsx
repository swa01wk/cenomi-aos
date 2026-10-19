import { useCallback, useEffect, useState } from "react";

export function initials(name: string): string {
  const words = name.split(/\s+/).filter(Boolean);
  const capitalised = words.filter((w) => /^[A-Z]/.test(w));
  return (capitalised.length >= 2 ? capitalised : words)
    .slice(0, 2)
    .map((w) => w[0]!.toUpperCase())
    .join("");
}

/** USD amount with cents; a spend above zero but under a cent reads "< 0.01", not "0.00". */
export function usdAmount(n: number): string {
  if (n > 0 && n < 0.005) return "< 0.01";
  return n.toFixed(2);
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

/** Load once on mount (and on `reload()`), exposing data, error and loading. */
export function useLoad<T>(load: () => Promise<T>, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
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
