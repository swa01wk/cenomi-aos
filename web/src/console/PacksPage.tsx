import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { Link, useOutletContext } from "react-router";
import { client } from "../api/client";
import type { Problem } from "../api/problems";
import { ApiProblemError } from "../api/problems";
import type { components } from "../api/schema";
import {
  Button,
  DataTable,
  ErrorBanner,
  PageHeader,
  Panel,
  ProblemNotice,
  Skeleton,
  StatusPill,
} from "../components";
import { newClientTurnId } from "../components/clientTurnId";
import { shortHash, when } from "../lib/ui";
import { PublishRequestPanel } from "./PublishRequestPanel";
import { useOrgPeople } from "./useOrgPeople";

type ValidationReport = components["schemas"]["ValidationReport"];
type StoredPackVersion = NonNullable<
  NonNullable<components["schemas"]["PackListing"]["packs"][number]["versions"]>[number]
>;
type PublishRequest = components["schemas"]["PublishRequest"];

const COUNT_ORDER = [
  "Role",
  "Seat",
  "Skill",
  "WorkflowDefinition",
  "Policy",
  "Verifier",
  "ArtifactType",
  "Resource",
  "ToolProvider",
  "EvalSuite",
  "files",
];

export function ReportView({ report }: { report: ValidationReport }) {
  const issues = [...report.errors, ...report.warnings];
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <div className={`banner ${report.ok ? "ok" : "bad"}`} role="status">
        <strong>{report.ok ? "Valid" : "Not valid"}</strong>
        <span>
          {report.pack} v{report.version} · {report.errors.length} errors, {report.warnings.length} warnings · digest{" "}
          <span className="mono">{shortHash(report.digest, 12)}</span>
        </span>
      </div>
      <div className="chips">
        {COUNT_ORDER.filter((k) => k in report.counts)
          .map((k) => [k, report.counts[k]] as const)
          .map(([k, v]) => (
            <span key={k} className="pill">
              {k} {v}
            </span>
          ))}
      </div>
      {issues.length > 0 && (
        <DataTable
          caption="Validation issues"
          rows={issues.map((issue, idx) => ({ issue, idx }))}
          getRowKey={(r) => `${r.issue.code}-${r.idx}`}
          columns={[
            {
              id: "severity",
              header: "Severity",
              render: (r) => (
                <span className={`pill ${r.issue.severity === "error" ? "bad" : "warn"}`}>{r.issue.severity}</span>
              ),
            },
            { id: "code", header: "Code", render: (r) => <span className="mono">{r.issue.code}</span> },
            {
              id: "where",
              header: "Where",
              render: (r) => (
                <span className="mono">
                  {r.issue.file}
                  {r.issue.path && `:${r.issue.path}`}
                </span>
              ),
            },
            { id: "message", header: "Problem", render: (r) => r.issue.message },
          ]}
        />
      )}
    </div>
  );
}

function VersionBlock({
  version,
  packName,
  requests,
  personName,
  onRequestPublish,
  onApprove,
  onReject,
  publishBusy,
}: {
  version: StoredPackVersion;
  packName: string;
  requests?: PublishRequest[];
  personName: (id: string) => string;
  onRequestPublish: (versionId: string) => Promise<void>;
  onApprove: (requestId: string, part: PublishRequest["parts"][number]["part"]) => Promise<void>;
  onReject: (requestId: string, reason: string) => Promise<void>;
  publishBusy: string | null;
}) {
  const canRequest = version.status === "validated";
  const busyKey = `publish:${version.id}`;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12, padding: "12px 0", borderTop: "1px solid var(--line)" }}>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 12, alignItems: "center" }}>
        <Link to={`/console/versions/${version.id}`} className="mono">
          v{version.version}
        </Link>
        <StatusPill state={version.status ?? ""} />
        <span className="mono muted">{shortHash(version.digest ?? "")}</span>
        <span className="muted">
          {version.errors} errors · {version.warnings} warnings
        </span>
        <span>{version.source}</span>
        <span>{personName(version.created_by ?? "")}</span>
        <span className="muted">{when(version.created_at ?? "")}</span>
        {canRequest && (
          <Button
            variant="primary"
            disabledReason={publishBusy !== null ? "Another action is in progress" : undefined}
            onClick={() => void onRequestPublish(version.id!)}
          >
            {publishBusy === busyKey ? "Requesting…" : "Request publish"}
          </Button>
        )}
      </div>
      {(requests ?? []).map((request) => (
        <PublishRequestPanel
          key={request.id}
          request={request}
          packVersionLabel={`${packName} v${version.version}`}
          personName={personName}
          showImmutableNote={version.status === "published" || request.status === "approved"}
          onApprove={(part) => onApprove(request.id, part)}
          onReject={(reason) => onReject(request.id, reason)}
        />
      ))}
      {version.status === "published" && !(requests?.length) && (
        <p className="muted" style={{ margin: 0, fontSize: 12 }}>
          Published versions are immutable. A change becomes the next version; running work stays on the version it
          started with.
        </p>
      )}
    </div>
  );
}

export default function PacksPage() {
  const { canSync } = useOutletContext<{ canSync: boolean }>();
  const queryClient = useQueryClient();
  const { personName } = useOrgPeople();
  const idempotencyKeys = useRef<Map<string, string>>(new Map());

  const { data, error, isPending } = useQuery({
    queryKey: ["packs"],
    queryFn: async () => {
      const { data: listing } = await client.GET("/console/packs");
      return listing!;
    },
  });

  const publishRequestsQuery = useQuery({
    queryKey: ["publishRequests"],
    queryFn: async () => {
      const { data: listing } = await client.GET("/console/publish-requests");
      return listing!.items;
    },
  });

  const requestsByVersion = new Map<string, PublishRequest[]>();
  if (publishRequestsQuery.data) {
    for (const req of publishRequestsQuery.data) {
      const list = requestsByVersion.get(req.pack_version_id) ?? [];
      list.push(req);
      requestsByVersion.set(req.pack_version_id, list);
    }
  }

  const [busy, setBusy] = useState<string | null>(null);
  const [result, setResult] = useState<{ name: string; report: ValidationReport; note?: string } | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const [actionProblem, setActionProblem] = useState<Problem | null>(null);

  const invalidateAll = () => {
    void queryClient.invalidateQueries({ queryKey: ["packs"] });
    void queryClient.invalidateQueries({ queryKey: ["publishRequests"] });
  };

  const runValidate = useMutation({
    mutationFn: async (name: string) => {
      const { data: report } = await client.POST("/console/packs/{name}/validate", { params: { path: { name } } });
      return { name, report: report! };
    },
    onSuccess: ({ name, report }) => {
      setResult({ name, report });
      setFailure(null);
      setActionProblem(null);
    },
    onError: (e: Error) => handleMutationError(e),
  });

  const runSync = useMutation({
    mutationFn: async (name: string) => {
      const { data: r } = await client.POST("/console/packs/{name}/sync", {
        params: { path: { name } },
        body: { source: "console" },
      });
      return { name, r: r! };
    },
    onSuccess: ({ name, r }) => {
      setResult({
        name,
        report: r.report,
        note: r.created
          ? `Stored as ${r.pack} v${r.version} (${r.status}).`
          : `Already stored: ${r.pack} v${r.version}, same digest.`,
      });
      setFailure(null);
      setActionProblem(null);
      invalidateAll();
    },
    onError: (e: Error) => handleMutationError(e),
  });

  const handleMutationError = (e: Error) => {
    if (e instanceof ApiProblemError) {
      setActionProblem(e.problem);
      setFailure(null);
      if (e.problem.status === 409) invalidateAll();
      return;
    }
    setActionProblem(null);
    setFailure(e.message);
  };

  const act = async (name: string, kind: "validate" | "sync") => {
    setBusy(`${kind}:${name}`);
    try {
      if (kind === "validate") await runValidate.mutateAsync(name);
      else await runSync.mutateAsync(name);
    } finally {
      setBusy(null);
    }
  };

  const requestPublish = async (versionId: string) => {
    setBusy(`publish:${versionId}`);
    setActionProblem(null);
    if (!idempotencyKeys.current.has(versionId)) {
      idempotencyKeys.current.set(versionId, newClientTurnId());
    }
    const key = idempotencyKeys.current.get(versionId)!;
    try {
      await client.POST("/console/pack-versions/{version_id}/publish-requests", {
        params: { path: { version_id: versionId }, header: { "Idempotency-Key": key } },
      });
      idempotencyKeys.current.delete(versionId);
      invalidateAll();
    } catch (e) {
      if (e instanceof ApiProblemError) setActionProblem(e.problem);
      else setFailure((e as Error).message);
    } finally {
      setBusy(null);
    }
  };

  const approvePart = async (requestId: string, part: PublishRequest["parts"][number]["part"]) => {
    setActionProblem(null);
    try {
      await client.POST("/console/publish-requests/{id}/approve", {
        params: { path: { id: requestId } },
        body: { part },
      });
      invalidateAll();
    } catch (e) {
      if (e instanceof ApiProblemError) setActionProblem(e.problem);
      else setFailure((e as Error).message);
    }
  };

  const rejectRequest = async (requestId: string, reason: string) => {
    setActionProblem(null);
    try {
      await client.POST("/console/publish-requests/{id}/reject", {
        params: { path: { id: requestId } },
        body: { reason },
      });
      invalidateAll();
    } catch (e) {
      if (e instanceof ApiProblemError && e.problem.status === 422) throw e;
      if (e instanceof ApiProblemError) setActionProblem(e.problem);
      else setFailure((e as Error).message);
    }
  };

  if (error) return <ErrorBanner title="We couldn't load packs" detail={(error as Error).message} />;
  if (isPending || !data) return <Skeleton />;
  const stored = new Map(data.packs.map((p) => [p.name, p]));

  return (
    <>
      <PageHeader
        eyebrow="Define · Domain packs"
        title="Domain packs"
        subtitle="A pack is the YAML that defines a digital worker: its Seat, Skills, verifiers, connectors, policies and workflow. Sync stores a version; publishing needs Risk and the pack owner to approve."
      />

      {actionProblem && (
        <ProblemNotice
          problem={actionProblem}
          onReload={() => {
            setActionProblem(null);
            invalidateAll();
          }}
        />
      )}
      {failure && <ErrorBanner title="Request failed" detail={failure} />}

      <section aria-label="Packs" style={{ display: "flex", flexDirection: "column", gap: 16 }}>
        {data.available.map((name) => {
          const p = stored.get(name);
          return (
            <Panel
              key={name}
              title={name}
              header={
                <div style={{ display: "flex", gap: 8 }}>
                  <Button type="button" onClick={() => act(name, "validate")} disabledReason={busy !== null ? "Another action is in progress" : undefined}>
                    {busy === `validate:${name}` ? "Validating…" : "Validate"}
                  </Button>
                  <Button
                    variant="primary"
                    onClick={() => act(name, "sync")}
                    disabledReason={
                      busy !== null
                        ? "Another action is in progress"
                        : !canSync
                          ? "Needs platform admin, process owner or Seat owner"
                          : undefined
                    }
                  >
                    {busy === `sync:${name}` ? "Syncing…" : "Sync from folder"}
                  </Button>
                </div>
              }
            >
              <span className="muted">packs/{name}{p?.owner ? ` · owner ${personName(p.owner)}` : ""}</span>
              {result?.name === name && (
                <div style={{ marginTop: 16 }}>
                  {result.note && <p style={{ marginTop: 0 }}>{result.note}</p>}
                  <ReportView report={result.report} />
                </div>
              )}
              {(p?.versions?.length ?? 0) > 0 ? (
                <div style={{ marginTop: 16 }}>
                  {(p!.versions ?? []).map((v) => (
                    <VersionBlock
                      key={v.id}
                      version={v}
                      packName={name}
                      requests={requestsByVersion.get(v.id!)}
                      personName={personName}
                      onRequestPublish={requestPublish}
                      onApprove={approvePart}
                      onReject={rejectRequest}
                      publishBusy={busy}
                    />
                  ))}
                </div>
              ) : (
                <p className="muted" style={{ marginTop: 16 }}>
                  Not stored yet. Sync it to create version 1.
                </p>
              )}
            </Panel>
          );
        })}
      </section>
    </>
  );
}
