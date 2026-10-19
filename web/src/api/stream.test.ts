import { describe, expect, it } from "vitest";
import { parseStreamSeq } from "./eventSeq";
import {
  applySseIdToCursor,
  backoffDelayMs,
  classifyStreamHttpStatus,
  createSseParser,
  recordDeltaSeq,
  shouldApplyDelta,
  shouldApplyOutboxEvent,
  snapshotRequiredPolicy,
} from "./stream";

describe("parseStreamSeq", () => {
  it("orders by numeric seq after the last colon", () => {
    expect(parseStreamSeq("instance:QQ-0001:9")).toBe(9);
    expect(parseStreamSeq("instance:QQ-0001:10")).toBe(10);
    expect(parseStreamSeq("instance:QQ-0001:10")! > parseStreamSeq("instance:QQ-0001:9")!).toBe(true);
    expect("instance:QQ-0001:10" > "instance:QQ-0001:9").toBe(false);
  });
});

describe("SSE parser", () => {
  it("handles chunk boundaries mid-line and multi-line data", () => {
    const events: unknown[] = [];
    const parser = createSseParser((d) => events.push(d.payload));

    const chunk1 = 'id: instance:x:1\nda';
    const chunk2 = 'ta: {"id":"instance:x:1","type":"turn.created","at":"t","data":{}}\n\n';
    parser.feed(chunk1);
    parser.feed(chunk2);
    expect(events).toHaveLength(1);

    parser.feed('data: line1\n');
    parser.feed("data: line2\n\n");
    expect(events).toHaveLength(1);

    const multi =
      'id: instance:x:2\ndata: {"id":"instance:x:2","type":"ping","at":"t","data":{"a":1}}\n\n';
    parser.feed(multi.slice(0, 20));
    parser.feed(multi.slice(20));
    expect(events).toHaveLength(2);
  });

  it("parses delta frames without sse id", () => {
    const out: { eventType?: string; sseId?: string }[] = [];
    const parser = createSseParser((d) =>
      out.push({ eventType: d.eventType, sseId: d.sseId }),
    );
    parser.feed(
      'event: agent.message.delta\ndata: {"id":"instance:i:d:t:1","type":"agent.message.delta","at":"t","data":{"turn_id":"t1","seq":1,"text":"Hi"}}\n\n',
    );
    expect(out[0]?.eventType).toBe("agent.message.delta");
    expect(out[0]?.sseId).toBeUndefined();
  });
});

describe("outbox dedupe", () => {
  it("ignores events with seq <= last applied", () => {
    let state = { lastAppliedSeq: 5, lastSseId: "instance:j:5" as string | undefined };
    const older = {
      id: "instance:j:4",
      type: "turn.created",
      at: "t",
      data: {},
    };
    expect(shouldApplyOutboxEvent(older, state).apply).toBe(false);

    const dup = { id: "instance:j:5", type: "turn.created", at: "t", data: {} };
    expect(shouldApplyOutboxEvent(dup, state).apply).toBe(false);

    const newer = { id: "instance:j:6", type: "turn.created", at: "t", data: {} };
    const r = shouldApplyOutboxEvent(newer, state);
    expect(r.apply).toBe(true);
    state = r.next;
    expect(state.lastAppliedSeq).toBe(6);
  });

  it("does not advance cursor state for deltas", () => {
    const state = { lastAppliedSeq: 3, lastSseId: "instance:j:3" };
    const delta = {
      id: "instance:uuid:d:turn:99",
      type: "agent.message.delta",
      at: "t",
      data: { turn_id: "turn", seq: 99, text: "x" },
    };
    expect(shouldApplyOutboxEvent(delta, state)).toEqual({ apply: true, next: state });
  });
});

describe("delta dedupe", () => {
  it("dedupes by turn_id and seq only", () => {
    const map = new Map<string, number>();
    expect(shouldApplyDelta("t1", 1, map)).toBe(true);
    recordDeltaSeq("t1", 1, map);
    expect(shouldApplyDelta("t1", 1, map)).toBe(false);
    expect(shouldApplyDelta("t1", 0, map)).toBe(false);
    expect(shouldApplyDelta("t2", 1, map)).toBe(true);
  });
});

describe("applySseIdToCursor", () => {
  it("updates lastSseId from sse id line", () => {
    const next = applySseIdToCursor("instance:a:7", { lastAppliedSeq: 6, lastSseId: "instance:a:6" });
    expect(next.lastAppliedSeq).toBe(7);
    expect(next.lastSseId).toBe("instance:a:7");
  });
});

describe("reconnect policy", () => {
  it("classifies HTTP statuses", () => {
    expect(classifyStreamHttpStatus(401)).toBe("unauthorized");
    expect(classifyStreamHttpStatus(403)).toBe("forbidden");
    expect(classifyStreamHttpStatus(404)).toBe("not_found");
    expect(classifyStreamHttpStatus(503)).toBe("retry");
    expect(classifyStreamHttpStatus(418)).toBe("stop");
  });

  it("uses 1/2/5/10 s backoff", () => {
    expect(backoffDelayMs(0)).toBe(1000);
    expect(backoffDelayMs(1)).toBe(2000);
    expect(backoffDelayMs(2)).toBe(5000);
    expect(backoffDelayMs(3)).toBe(10000);
    expect(backoffDelayMs(9)).toBe(10000);
  });

  it("backs off before refetch when snapshot.required repeats for the same cursor", () => {
    const first = snapshotRequiredPolicy({
      cursor: "instance:x:10",
      lastRequiredAtCursor: null,
      repeatCount: 0,
    });
    expect(first.shouldBackoffBeforeRefetch).toBe(false);

    const second = snapshotRequiredPolicy({
      cursor: "instance:x:10",
      lastRequiredAtCursor: "instance:x:10",
      repeatCount: 0,
    });
    expect(second.shouldBackoffBeforeRefetch).toBe(false);

    const third = snapshotRequiredPolicy({
      cursor: "instance:x:10",
      lastRequiredAtCursor: "instance:x:10",
      repeatCount: 1,
    });
    expect(third.shouldBackoffBeforeRefetch).toBe(true);
  });
});

describe("reconnect cursor", () => {
  it("does not move resume id on delta-only traffic", () => {
    let state = { lastAppliedSeq: 2, lastSseId: "instance:z:2" as string | undefined };
    const parser = createSseParser(({ payload, sseId }) => {
      if (payload.type === "agent.message.delta") return;
      state = applySseIdToCursor(sseId, state);
      const r = shouldApplyOutboxEvent(payload, state);
      if (r.apply) state = r.next;
    });

    parser.feed(
      'event: agent.message.delta\ndata: {"id":"ephemeral","type":"agent.message.delta","at":"t","data":{"turn_id":"a","seq":1,"text":"x"}}\n\n',
    );
    expect(state.lastSseId).toBe("instance:z:2");

    parser.feed(
      'id: instance:z:3\ndata: {"id":"instance:z:3","type":"turn.created","at":"t","data":{}}\n\n',
    );
    expect(state.lastSseId).toBe("instance:z:3");
  });
});
