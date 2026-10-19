import { useCallback, useEffect, useRef, useState } from "react";
import { getToken } from "./session";
import { parseProblem, type Problem } from "./problems";
import { handleUnauthorized } from "./client";
import { isDeltaEventType, parseStreamSeq } from "./eventSeq";

export type UiEvent = {
  id: string;
  type: string;
  at: string;
  instance_id?: string | null;
  data: Record<string, unknown>;
};

export type SseFrame = {
  sseId?: string;
  event?: string;
  data: string;
};

export type ParsedSseDispatch = {
  sseId?: string;
  eventType?: string;
  payload: UiEvent;
};

const BACKOFF_MS = [1000, 2000, 5000, 10000] as const;

export function backoffDelayMs(attempt: number): number {
  return BACKOFF_MS[Math.min(attempt, BACKOFF_MS.length - 1)]!;
}

export type StreamHttpFailure = "unauthorized" | "forbidden" | "not_found" | "retry" | "stop";

export function classifyStreamHttpStatus(status: number): StreamHttpFailure {
  if (status === 401) return "unauthorized";
  if (status === 403) return "forbidden";
  if (status === 404) return "not_found";
  if (status >= 500) return "retry";
  return "stop";
}

export type SnapshotRequiredPolicyInput = {
  cursor: string;
  lastRequiredAtCursor: string | null;
  repeatCount: number;
};

export type SnapshotRequiredPolicy = {
  shouldBackoffBeforeRefetch: boolean;
  nextRepeatCount: number;
  nextLastRequiredAtCursor: string;
};

/** If snapshot.required fires again for the same cursor, back off before the next reload. */
export function snapshotRequiredPolicy(input: SnapshotRequiredPolicyInput): SnapshotRequiredPolicy {
  const same = input.lastRequiredAtCursor === input.cursor;
  const nextRepeatCount = same ? input.repeatCount + 1 : 0;
  return {
    shouldBackoffBeforeRefetch: same && input.repeatCount > 0,
    nextRepeatCount,
    nextLastRequiredAtCursor: input.cursor,
  };
}

export function createSseParser(onDispatch: (frame: ParsedSseDispatch) => void) {
  let buf = "";
  let sseId: string | undefined;
  let eventName: string | undefined;
  const dataLines: string[] = [];

  const dispatch = () => {
    if (!dataLines.length) {
      sseId = undefined;
      eventName = undefined;
      return;
    }
    const raw = dataLines.join("\n");
    dataLines.length = 0;
    let payload: UiEvent;
    try {
      payload = JSON.parse(raw) as UiEvent;
    } catch {
      sseId = undefined;
      eventName = undefined;
      return;
    }
    const eventType = eventName ?? payload.type;
    onDispatch({ sseId, eventType, payload });
    sseId = undefined;
    eventName = undefined;
  };

  const feed = (chunk: string) => {
    buf += chunk;
    for (;;) {
      const nl = buf.indexOf("\n");
      if (nl < 0) break;
      let line = buf.slice(0, nl);
      buf = buf.slice(nl + 1);
      if (line.endsWith("\r")) line = line.slice(0, -1);

      if (line === "") {
        dispatch();
        continue;
      }
      if (line.startsWith(":")) continue;
      if (line.startsWith("id:")) {
        sseId = line.slice(3).trimStart();
        continue;
      }
      if (line.startsWith("event:")) {
        eventName = line.slice(6).trimStart();
        continue;
      }
      if (line.startsWith("data:")) {
        dataLines.push(line.slice(5).trimStart());
      }
    }
  };

  return { feed, flush: dispatch };
}

export type StreamCursorState = {
  lastAppliedSeq: number;
  lastSseId: string | undefined;
};

export function shouldApplyOutboxEvent(
  event: UiEvent,
  state: StreamCursorState,
): { apply: boolean; next: StreamCursorState } {
  if (isDeltaEventType(event.type)) {
    return { apply: true, next: state };
  }
  const seq = parseStreamSeq(event.id);
  if (seq == null) return { apply: true, next: state };
  if (seq <= state.lastAppliedSeq) return { apply: false, next: state };
  return {
    apply: true,
    next: {
      lastAppliedSeq: seq,
      lastSseId: event.id,
    },
  };
}

export type StreamRoute =
  | { kind: "delta" }
  | { kind: "snapshot_required" }
  | { kind: "apply"; next: StreamCursorState }
  | { kind: "skip" };

/**
 * Decide what to do with one dispatched SSE event.
 * - deltas never touch the cursor (their id is ephemeral);
 * - snapshot.required always goes through, whatever its seq (a gap reports an older seq);
 * - outbox events apply only when their seq is past the last applied one, and then move the cursor.
 */
export function routeStreamEvent(event: UiEvent, state: StreamCursorState): StreamRoute {
  if (isDeltaEventType(event.type)) return { kind: "delta" };
  if (event.type === "snapshot.required") return { kind: "snapshot_required" };
  const { apply, next } = shouldApplyOutboxEvent(event, state);
  return apply ? { kind: "apply", next } : { kind: "skip" };
}

export function applySseIdToCursor(sseId: string | undefined, state: StreamCursorState): StreamCursorState {
  if (!sseId) return state;
  const seq = parseStreamSeq(sseId);
  if (seq == null || seq <= state.lastAppliedSeq) return state;
  return { lastAppliedSeq: seq, lastSseId: sseId };
}

export type DeltaKey = `${string}:${number}`;

export function deltaKey(turnId: string, seq: number): DeltaKey {
  return `${turnId}:${seq}`;
}

export function shouldApplyDelta(
  turnId: string,
  seq: number,
  lastSeqByTurn: Map<string, number>,
): boolean {
  const last = lastSeqByTurn.get(turnId) ?? -1;
  return seq > last;
}

export function recordDeltaSeq(turnId: string, seq: number, lastSeqByTurn: Map<string, number>): void {
  const last = lastSeqByTurn.get(turnId) ?? -1;
  if (seq > last) lastSeqByTurn.set(turnId, seq);
}

function apiBaseUrl(): string {
  if (typeof window !== "undefined" && window.location?.origin && window.location.origin !== "null") {
    return `${window.location.origin}/api`;
  }
  return "/api";
}

export type UseEventStreamOptions = {
  instanceId: string;
  cursor: string | null;
  paused?: boolean;
  enabled?: boolean;
  onEvent: (event: UiEvent) => void;
  onStreamProblem?: (problem: Problem) => void;
  onNeedsSnapshot?: () => void | Promise<void>;
};

export type EventStreamStatus = "idle" | "connected" | "reconnecting";

export function useEventStream({
  instanceId,
  cursor,
  paused = false,
  enabled = true,
  onEvent,
  onStreamProblem,
  onNeedsSnapshot,
}: UseEventStreamOptions): {
  status: EventStreamStatus;
  updatesWhileDisconnected: number;
} {
  const [status, setStatus] = useState<EventStreamStatus>("idle");
  const [updatesWhileDisconnected, setUpdatesWhileDisconnected] = useState(0);

  const onEventRef = useRef(onEvent);
  const onStreamProblemRef = useRef(onStreamProblem);
  const onNeedsSnapshotRef = useRef(onNeedsSnapshot);
  onEventRef.current = onEvent;
  onStreamProblemRef.current = onStreamProblem;
  onNeedsSnapshotRef.current = onNeedsSnapshot;

  const cursorStateRef = useRef<StreamCursorState>({ lastAppliedSeq: -1, lastSseId: undefined });
  const deltaSeqRef = useRef(new Map<string, number>());
  const snapshotRequiredRef = useRef({ lastCursor: null as string | null, repeat: 0 });
  const reconnectAttemptRef = useRef(0);
  const disconnectedRef = useRef(false);
  const pendingUpdatesRef = useRef(0);

  useEffect(() => {
    const seq = cursor ? parseStreamSeq(cursor) : null;
    cursorStateRef.current = {
      lastAppliedSeq: seq ?? -1,
      lastSseId: cursor ?? undefined,
    };
    deltaSeqRef.current = new Map();
    snapshotRequiredRef.current = { lastCursor: null, repeat: 0 };
    reconnectAttemptRef.current = 0;
    disconnectedRef.current = false;
    pendingUpdatesRef.current = 0;
    setUpdatesWhileDisconnected(0);
  }, [instanceId, cursor]);

  const handleUiEvent = useCallback((dispatch: ParsedSseDispatch) => {
    const { payload, sseId } = dispatch;
    if (isDeltaEventType(payload.type)) {
      const data = payload.data as { turn_id?: string; seq?: number };
      const turnId = data.turn_id;
      const seq = data.seq;
      if (turnId != null && seq != null && !shouldApplyDelta(turnId, seq, deltaSeqRef.current)) {
        return;
      }
      if (turnId != null && seq != null) recordDeltaSeq(turnId, seq, deltaSeqRef.current);
      if (disconnectedRef.current) pendingUpdatesRef.current += 1;
      onEventRef.current(payload);
      return;
    }

    void sseId; // the payload id is the same cursor the SSE id: line carries
    const route = routeStreamEvent(payload, cursorStateRef.current);
    if (route.kind === "skip") return;

    if (route.kind === "snapshot_required") {
      void (async () => {
        const cur = cursor ?? "";
        const pol = snapshotRequiredPolicy({
          cursor: cur,
          lastRequiredAtCursor: snapshotRequiredRef.current.lastCursor,
          repeatCount: snapshotRequiredRef.current.repeat,
        });
        snapshotRequiredRef.current = {
          lastCursor: pol.nextLastRequiredAtCursor,
          repeat: pol.nextRepeatCount,
        };
        if (pol.shouldBackoffBeforeRefetch) {
          await new Promise((r) => setTimeout(r, backoffDelayMs(reconnectAttemptRef.current)));
          reconnectAttemptRef.current += 1;
        }
        await onNeedsSnapshotRef.current?.();
      })();
      return;
    }

    if (route.kind === "apply") cursorStateRef.current = route.next;
    if (disconnectedRef.current) pendingUpdatesRef.current += 1;
    onEventRef.current(payload);
  }, [cursor]);

  useEffect(() => {
    if (!enabled || !instanceId || paused) {
      setStatus("idle");
      return;
    }

    const abort = new AbortController();
    let timeoutId: ReturnType<typeof setTimeout> | undefined;
    let closed = false;

    const run = async () => {
      while (!closed && !abort.signal.aborted) {
        const token = getToken();
        if (!token) break;

        const headers: Record<string, string> = {
          Authorization: `Bearer ${token}`,
          Accept: "text/event-stream",
        };
        const resume = cursorStateRef.current.lastSseId ?? cursor;
        if (resume) headers["Last-Event-ID"] = resume;

        const url = `${apiBaseUrl()}/instances/${encodeURIComponent(instanceId)}/events`;
        setStatus(reconnectAttemptRef.current > 0 ? "reconnecting" : "connected");

        try {
          const res = await fetch(url, { headers, signal: abort.signal });
          if (!res.ok) {
            const problem = await parseProblem(res);
            const kind = classifyStreamHttpStatus(res.status);
            if (kind === "unauthorized") {
              handleUnauthorized(problem ?? undefined);
              return;
            }
            if (kind === "forbidden" || kind === "not_found") {
              if (problem) onStreamProblemRef.current?.(problem);
              setStatus("idle");
              return;
            }
            if (kind === "retry") {
              disconnectedRef.current = true;
              setStatus("reconnecting");
              const delay = backoffDelayMs(reconnectAttemptRef.current);
              reconnectAttemptRef.current += 1;
              await new Promise((r) => {
                timeoutId = setTimeout(r, delay);
              });
              continue;
            }
            setStatus("idle");
            return;
          }

          reconnectAttemptRef.current = 0;
          disconnectedRef.current = false;
          if (pendingUpdatesRef.current > 0) {
            setUpdatesWhileDisconnected(pendingUpdatesRef.current);
            pendingUpdatesRef.current = 0;
          }
          setStatus("connected");

          const body = res.body;
          if (!body) {
            disconnectedRef.current = true;
            setStatus("reconnecting");
            const delay = backoffDelayMs(reconnectAttemptRef.current++);
            await new Promise((r) => {
              timeoutId = setTimeout(r, delay);
            });
            continue;
          }

          const parser = createSseParser(handleUiEvent);
          const reader = body.getReader();
          const decoder = new TextDecoder();

          for (;;) {
            const { done, value } = await reader.read();
            if (done) break;
            parser.feed(decoder.decode(value, { stream: true }));
          }
          parser.flush();

          disconnectedRef.current = true;
          setStatus("reconnecting");
          const delay = backoffDelayMs(reconnectAttemptRef.current++);
          await new Promise((r) => {
            timeoutId = setTimeout(r, delay);
          });
        } catch (e) {
          if (abort.signal.aborted) return;
          disconnectedRef.current = true;
          setStatus("reconnecting");
          const delay = backoffDelayMs(reconnectAttemptRef.current++);
          await new Promise((r) => {
            timeoutId = setTimeout(r, delay);
          });
        }
      }
    };

    void run();

    return () => {
      closed = true;
      abort.abort();
      if (timeoutId) clearTimeout(timeoutId);
    };
  }, [instanceId, cursor, paused, enabled, handleUiEvent]);

  return { status, updatesWhileDisconnected };
}
