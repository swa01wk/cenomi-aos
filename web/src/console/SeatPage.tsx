import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams } from "react-router";
import { client } from "../api/client";
import { ApiProblemError, type Problem } from "../api/problems";
import type { components } from "../api/schema";
import {
  Button,
  CheckList,
  checksFromSeatDetail,
  ErrorBanner,
  LifecycleSteps,
  PageHeader,
  Panel,
  ProblemNotice,
  Skeleton,
  StatusPill,
} from "../components";
import { when } from "../lib/ui";
import { buildSeatLifecycleSteps } from "./seatLifecycleSteps";
import { useOrgPeople } from "./useOrgPeople";

type SeatDetail = components["schemas"]["SeatDetail"];

function evalStatusLabel(run: components["schemas"]["EvalRun"]): string {
  if (run.status === "running") return "Running";
  if (run.status === "failed") return "Failed";
  if (run.passed != null && run.total != null) return `${run.passed} / ${run.total}`;
  return "Pass";
}

export default function SeatPage() {
  const { seat: seatParam } = useParams<{ seat: string }>();
  const seatName = seatParam ? decodeURIComponent(seatParam) : "";
  const queryClient = useQueryClient();
  const { personName } = useOrgPeople();
  const [actionError, setActionError] = useState<Problem | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const seatQuery = useQuery({
    queryKey: ["seat", seatName],
    enabled: Boolean(seatName),
    queryFn: async () => {
      const { data } = await client.GET("/console/seats/{seat}", { params: { path: { seat: seatName } } });
      return data!;
    },
    refetchInterval: (query) => {
      const seat = query.state.data as SeatDetail | undefined;
      const running = seat?.evals?.some((e) => e.status === "running");
      return running ? 1500 : false;
    },
  });

  const invalidateSeat = () => queryClient.invalidateQueries({ queryKey: ["seat", seatName] });

  const lifecycleBody = (s: SeatDetail) => ({
    version: s.version,
    expected_version: s.record_version ?? 0,
  });

  const runAction = async (key: string, fn: () => Promise<void>) => {
    setBusy(key);
    setActionError(null);
    try {
      await fn();
      await invalidateSeat();
    } catch (e) {
      if (e instanceof ApiProblemError) setActionError(e.problem);
      else setActionError({ type: "about:blank", title: "Request failed", status: 500, code: "internal", detail: (e as Error).message });
    } finally {
      setBusy(null);
    }
  };

  const configure = useMutation({
    mutationFn: async (s: SeatDetail) => {
      const { data } = await client.POST("/console/seats/{seat}/configure", {
        params: { path: { seat: seatName } },
        body: lifecycleBody(s),
      });
      return data!;
    },
  });

  const runEvals = useMutation({
    mutationFn: async (s: SeatDetail) => {
      await client.POST("/console/seats/{seat}/evals", {
        params: { path: { seat: seatName } },
        body: { version: s.version, model: "fake" },
      });
    },
  });

  const approve = useMutation({
    mutationFn: async (s: SeatDetail) => {
      const { data } = await client.POST("/console/seats/{seat}/approve", {
        params: { path: { seat: seatName } },
        body: lifecycleBody(s),
      });
      return data!;
    },
  });

  const activate = useMutation({
    mutationFn: async (s: SeatDetail) => {
      const { data } = await client.POST("/console/seats/{seat}/activate", {
        params: { path: { seat: seatName } },
        body: lifecycleBody(s),
      });
      return data!;
    },
  });

  if (!seatName) return <ErrorBanner title="Missing seat" detail="No seat name in the URL." />;
  if (seatQuery.error) {
    return <ErrorBanner title="We couldn't load this seat" detail={(seatQuery.error as Error).message} />;
  }
  if (seatQuery.isPending || !seatQuery.data) return <Skeleton />;

  const seat = seatQuery.data;
  const checks = seat.checks ?? [];
  const passedChecks = checks.filter((c) => c.passed).length;
  const lifecycleSteps = buildSeatLifecycleSteps(seat.state, seat.history, (h) => {
    const by = personName(h.by);
    return h.at ? `${when(h.at)} · ${by}` : by;
  });

  const showConfigure = seat.state === "DRAFT";
  const showRunEvals = seat.state === "CONFIGURED" || seat.state === "TESTING";
  const showApprove = seat.state === "TESTING";
  const showActivate = seat.state === "APPROVED";

  return (
    <>
      <p className="muted" style={{ margin: "0 0 8px", fontSize: 12 }}>
        <Link to="/console/seats">Seats</Link> / <span className="mono">{seat.name}</span>
      </p>
      <PageHeader
        title={seat.display_name}
        actions={
          <div style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center" }}>
            <StatusPill state={seat.state} />
            <StatusPill state={seat.availability} />
            <span className="mono pill">v{seat.version}</span>
          </div>
        }
      />

      {actionError && (
        <ProblemNotice
          problem={actionError}
          onReload={() => {
            setActionError(null);
            void invalidateSeat();
          }}
        />
      )}

      <LifecycleSteps steps={lifecycleSteps} />

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(340px, 1fr))", gap: 16 }}>
        <Panel title="Configuration">
          <dl style={{ margin: "0 0 16px", display: "grid", gridTemplateColumns: "140px 1fr", gap: "8px 12px", fontSize: 13 }}>
            <dt className="muted">Placement</dt>
            <dd style={{ margin: 0 }} className="mono">
              {seat.placement}
            </dd>
            <dt className="muted">Configured by</dt>
            <dd style={{ margin: 0 }}>{seat.configured_by ? personName(seat.configured_by) : "—"}</dd>
            {seat.limits && (
              <>
                <dt className="muted">Limits</dt>
                <dd style={{ margin: 0 }}>
                  {seat.limits.run_minutes} min and {seat.limits.actions_per_run} actions per attempt · USD{" "}
                  {seat.limits.daily_cost_usd} a day
                </dd>
              </>
            )}
          </dl>
          <h3 style={{ margin: "0 0 8px", fontSize: 15, fontWeight: 600 }}>
            Configuration checks · {passedChecks} of {checks.length} pass
          </h3>
          <CheckList items={checksFromSeatDetail(checks)} />
        </Panel>

        <Panel title="Evaluation runs in the sandbox">
          {(seat.evals ?? []).length === 0 ? (
            <p className="muted" style={{ margin: 0 }}>
              No evaluation runs yet.
            </p>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              {(seat.evals ?? []).map((run) => (
                <div key={run.id} style={{ padding: 12, border: "1px solid var(--line)", borderRadius: 8 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
                    <span className="mono" style={{ fontWeight: 500, flex: 1 }}>
                      {run.suite}
                    </span>
                    <StatusPill state={run.status} />
                    <span className="pill">{run.model}</span>
                    <span className="pill">{evalStatusLabel(run)}</span>
                  </div>
                  {run.detail?.deferred_count != null && run.detail.deferred_count > 0 && (
                    <p className="muted" style={{ margin: 0, fontSize: 12 }}>
                      {run.detail.deferred_count} deferred expectation
                      {run.detail.deferred_count === 1 ? "" : "s"}
                    </p>
                  )}
                </div>
              ))}
            </div>
          )}
        </Panel>
      </div>

      <Panel title="Actions">
        <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
          {showConfigure && (
            <Button
              variant="primary"
              disabledReason={busy !== null ? "Another action is in progress" : undefined}
              onClick={() =>
                void runAction("configure", async () => {
                  await configure.mutateAsync(seat);
                })
              }
            >
              {busy === "configure" ? "Configuring…" : "Configure"}
            </Button>
          )}
          {showRunEvals && (
            <Button
              variant="primary"
              disabledReason={busy !== null ? "Another action is in progress" : undefined}
              onClick={() =>
                void runAction("evals", async () => {
                  await runEvals.mutateAsync(seat);
                })
              }
            >
              {busy === "evals" ? "Starting evals…" : "Run evals"}
            </Button>
          )}
          {showApprove && (
            <Button
              variant="secondary"
              disabledReason={busy !== null ? "Another action is in progress" : undefined}
              onClick={() =>
                void runAction("approve", async () => {
                  await approve.mutateAsync(seat);
                })
              }
            >
              {busy === "approve" ? "Approving…" : "Approve (Risk)"}
            </Button>
          )}
          {showActivate && (
            <Button
              variant="primary"
              disabledReason={busy !== null ? "Another action is in progress" : undefined}
              onClick={() =>
                void runAction("activate", async () => {
                  await activate.mutateAsync(seat);
                })
              }
            >
              {busy === "activate" ? "Activating…" : "Activate"}
            </Button>
          )}
        </div>
      </Panel>

    </>
  );
}
