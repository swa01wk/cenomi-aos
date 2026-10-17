// Thin client for the kernel API. The session token lives in sessionStorage (per tab, POC personas only).

export type Person = { id: string; name: string; team: string; roles: string[]; console: boolean };

export type Issue = { code: string; file: string; path: string; message: string; severity: string };

export type ValidationReport = {
  pack: string;
  version: number | null;
  digest: string;
  ok: boolean;
  counts: Record<string, number>;
  errors: Issue[];
  warnings: Issue[];
};

export type PackVersionRow = {
  id: string;
  version: number;
  digest: string;
  status: string;
  source: string;
  created_by: string;
  created_at: string;
  ok: boolean;
  errors: number;
  warnings: number;
};

export type PackListing = {
  available: string[];
  packs: { name: string; owner: string; versions: PackVersionRow[] }[];
};

export type SyncResult = {
  pack_version_id: string;
  pack: string;
  version: number;
  digest: string;
  status: string;
  created: boolean;
  report: ValidationReport;
};

export type PackVersion = {
  id: string;
  pack: string;
  version: number;
  digest: string;
  status: string;
  source: string;
  validation: ValidationReport;
  created_by: string;
  created_at: string;
  definitions: { kind: string; name: string; version: number; file: string; digest: string }[];
};

export type Org = {
  organization: { id: string; name: string; data_residency: string };
  departments: { id: string; name: string; head: string; teams: { id: string; name: string; owner: string }[] }[];
  people: { id: string; name: string; department: string; team: string; console: boolean; roles: string[] }[];
};

export type AuditRecord = {
  org_id: string;
  seq: number;
  occurred_at: string;
  actor: string;
  action: string;
  subject: string;
  correlation_id: string | null;
  data: Record<string, unknown>;
  prev_hash: string;
  record_hash: string;
};

export type ChainReport = {
  intact: boolean;
  records: number;
  head_hash: string;
  first_broken_seq: number | null;
  reason: string;
};

const KEY = "aos.session";

export type Session = { token: string; person: Person };

export function loadSession(): Session | null {
  try {
    const raw = sessionStorage.getItem(KEY);
    return raw ? (JSON.parse(raw) as Session) : null;
  } catch {
    return null;
  }
}

export function saveSession(s: Session | null): void {
  try {
    if (s) sessionStorage.setItem(KEY, JSON.stringify(s));
    else sessionStorage.removeItem(KEY);
  } catch {
    /* storage unavailable: the session lasts until reload */
  }
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

let token: string | null = loadSession()?.token ?? null;
let onUnauthorized: () => void = () => {};

export function setToken(t: string | null, unauthorized?: () => void): void {
  token = t;
  if (unauthorized) onUnauthorized = unauthorized;
}

async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = {};
  if (token) headers.Authorization = `Bearer ${token}`;
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const res = await fetch(`/api${path}`, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  if (res.status === 401) onUnauthorized();
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {
      /* not JSON */
    }
    throw new ApiError(res.status, typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return (await res.json()) as T;
}

export const api = {
  personas: () => call<Person[]>("GET", "/auth/personas"),
  signIn: (person_id: string) => call<Session>("POST", "/auth/session", { person_id }),
  org: () => call<Org>("GET", "/org"),
  packs: () => call<PackListing>("GET", "/console/packs"),
  validate: (name: string) => call<ValidationReport>("POST", `/console/packs/${name}/validate`),
  sync: (name: string) => call<SyncResult>("POST", `/console/packs/${name}/sync`, { source: "console" }),
  version: (id: string) => call<PackVersion>("GET", `/console/pack-versions/${id}`),
  definition: (id: string, kind: string, name: string) =>
    call<Record<string, unknown>>("GET", `/console/pack-versions/${id}/definitions/${kind}/${name}`),
  audit: (before?: number) =>
    call<{ items: AuditRecord[] }>("GET", `/console/audit?limit=50${before ? `&before_seq=${before}` : ""}`),
  verify: () => call<ChainReport>("POST", "/console/audit/verify"),
};
