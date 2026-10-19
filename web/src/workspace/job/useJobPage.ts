import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { client } from "../../api/client";
import { ApiProblemError, type Problem } from "../../api/problems";
import type { UiEvent } from "../../api/stream";
import { useEventStream } from "../../api/stream";
import { useSession } from "../../app/session";
import type { ToolActivity, Turn } from "../../components/types";
import { workspaceKeys } from "../useWorkspaceQueries";
import {
  emptyJobStreamAux,
  reduceJobStreamEvent,
  type InstanceSnapshot,
  type JobStreamAuxState,
} from "./jobStreamReducer";

function upsertTurn(turns: Turn[], turn: Turn): Turn[] {
  const i = turns.findIndex((t) => t.turn_id === turn.turn_id);
  if (i < 0) return [...turns, turn].sort((a, b) => a.seq - b.seq);
  const next = [...turns];
  next[i] = turn;
  return next.sort((a, b) => a.seq - b.seq);
}

export function useJobPage(instanceId: string) {
  const queryClient = useQueryClient();
  const { sessionExpired } = useSession();
  const auxRef = useRef<JobStreamAuxState>(emptyJobStreamAux());
  const [auxVersion, setAuxVersion] = useState(0);
  const [streamProblem, setStreamProblem] = useState<Problem | null>(null);
  const [bannerMode, setBannerMode] = useState<"hidden" | "reconnecting" | "synced">("hidden");
  const [syncCount, setSyncCount] = useState(0);

  const snapshotQuery = useQuery({
    queryKey: workspaceKeys.instance(instanceId),
    enabled: !sessionExpired,
    // The event stream keeps the snapshot current; a focus refetch would only race it.
    refetchOnWindowFocus: false,
    queryFn: async () => {
      const { data, error } = await client.GET("/instances/{id}", {
        params: { path: { id: instanceId } },
      });
      if (error) throw error;
      return data!;
    },
  });

  const resetAuxFromSnapshot = useCallback((snap: InstanceSnapshot) => {
    auxRef.current = emptyJobStreamAux(snap.cursor);
    setAuxVersion((n) => n + 1);
  }, []);

  const loadedRef = useRef(false);
  useEffect(() => {
    loadedRef.current = false;
  }, [instanceId]);

  useEffect(() => {
    if (snapshotQuery.data && !loadedRef.current) {
      resetAuxFromSnapshot(snapshotQuery.data);
      loadedRef.current = true;
    }
  }, [snapshotQuery.data, resetAuxFromSnapshot]);

  const applyEvent = useCallback(
    (event: UiEvent) => {
      const snap = queryClient.getQueryData<InstanceSnapshot>(workspaceKeys.instance(instanceId));
      if (!snap) return;
      const result = reduceJobStreamEvent(snap, auxRef.current, event);
      if (result.skip) return;
      queryClient.setQueryData(workspaceKeys.instance(instanceId), result.snapshot);
      auxRef.current = result.aux;
      setAuxVersion((n) => n + 1);
      for (const eff of result.effects) {
        if (eff.kind === "refetch_snapshot") {
          void snapshotQuery.refetch().then((r) => {
            if (r.data) resetAuxFromSnapshot(r.data);
          });
        }
        if (eff.kind === "invalidate_artifact") {
          void queryClient.invalidateQueries({ queryKey: workspaceKeys.artifact(eff.artifactId) });
        }
      }
    },
    [instanceId, queryClient, resetAuxFromSnapshot, snapshotQuery],
  );

  const onNeedsSnapshot = useCallback(async () => {
    const r = await snapshotQuery.refetch();
    if (r.data) resetAuxFromSnapshot(r.data);
  }, [resetAuxFromSnapshot, snapshotQuery]);

  const cursor = snapshotQuery.data?.cursor ?? null;
  const { status, updatesWhileDisconnected } = useEventStream({
    instanceId,
    cursor,
    paused: sessionExpired,
    enabled: Boolean(snapshotQuery.data) && !snapshotQuery.isError,
    onEvent: applyEvent,
    onStreamProblem: setStreamProblem,
    onNeedsSnapshot,
  });

  useEffect(() => {
    if (status === "reconnecting") setBannerMode("reconnecting");
    else if (updatesWhileDisconnected > 0) {
      setBannerMode("synced");
      setSyncCount(updatesWhileDisconnected);
    } else if (status === "connected") setBannerMode("hidden");
  }, [status, updatesWhileDisconnected]);

  const aux = auxRef.current;
  void auxVersion;

  const streamingTurnId = useMemo(() => {
    if (!aux.deltas.length) return null;
    return aux.deltas[aux.deltas.length - 1]!.turn_id;
  }, [aux.deltas, auxVersion]);

  const toolActivityForStream = useMemo((): ToolActivity | undefined => {
    const snap = snapshotQuery.data;
    const turn = streamingTurnId ? snap?.turns.find((t) => t.turn_id === streamingTurnId) : undefined;
    const attemptId = turn?.attempt_id;
    if (attemptId) return aux.toolActivityByAttempt.get(attemptId);
    return aux.toolActivityByAttempt.values().next().value;
  }, [aux.toolActivityByAttempt, snapshotQuery.data, streamingTurnId, auxVersion]);

  const loadOlderTurns = useCallback(async () => {
    const snap = snapshotQuery.data;
    if (!snap?.turns.length) return;
    const before = Math.min(...snap.turns.map((t) => t.seq));
    const { data, error } = await client.GET("/instances/{id}/turns", {
      params: { path: { id: instanceId }, query: { before_seq: before, limit: 50 } },
    });
    if (error) throw error;
    const older = data!.items;
    queryClient.setQueryData(workspaceKeys.instance(instanceId), {
      ...snap,
      turns: [...older, ...snap.turns].sort((a, b) => a.seq - b.seq),
    });
  }, [instanceId, queryClient, snapshotQuery.data]);

  const postTurn = useCallback(
    async (text: string, clientTurnId: string) => {
      const { data, error } = await client.POST("/instances/{id}/turns", {
        params: { path: { id: instanceId } },
        body: { text, client_turn_id: clientTurnId },
      });
      if (error) throw error;
      if (data?.turn) {
        queryClient.setQueryData(workspaceKeys.instance(instanceId), (snap: InstanceSnapshot | undefined) =>
          snap ? { ...snap, turns: upsertTurn(snap.turns, data.turn) } : snap,
        );
      }
    },
    [instanceId, queryClient],
  );

  const pageError =
    snapshotQuery.error instanceof ApiProblemError
      ? snapshotQuery.error.problem
      : snapshotQuery.error
        ? {
            type: "about:blank",
            title: "Can't load this job",
            detail: String(snapshotQuery.error),
            status: 500,
            code: "internal" as const,
          }
        : streamProblem;

  return {
    snapshot: snapshotQuery.data,
    isLoading: snapshotQuery.isLoading,
    pageError,
    postTurn,
    loadOlderTurns,
    streamingTurnId,
    deltas: aux.deltas,
    toolActivity: toolActivityForStream,
    bannerMode,
    syncCount,
    refetch: snapshotQuery.refetch,
  };
}
