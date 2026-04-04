import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useSSE } from "../useSSE";
import { MockEventSource } from "./helpers";

let lastCreatedES: MockEventSource | null = null;

beforeEach(() => {
  lastCreatedES = null;
  vi.stubGlobal(
    "EventSource",
    class extends MockEventSource {
      constructor(url: string) {
        super(url);
        lastCreatedES = this;
      }
    }
  );
  // Synchronous RAF for predictable test behavior
  vi.stubGlobal("requestAnimationFrame", (cb: () => void) => {
    cb();
    return 0;
  });
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("useSSE", () => {
  it("returns empty messages and disconnected when roomId is null", () => {
    const { result } = renderHook(() => useSSE(null));
    expect(result.current.messages).toEqual([]);
    expect(result.current.connectionStatus).toBe("disconnected");
  });

  it("connects to SSE endpoint with room ID", () => {
    const { result } = renderHook(() => useSSE("room-123"));
    expect(result.current.connectionStatus).toBe("connecting");
    expect(lastCreatedES?.url).toContain("room_id=room-123");
  });

  it("transitions to connected on open", () => {
    const { result } = renderHook(() => useSSE("room-123"));

    act(() => {
      lastCreatedES?._triggerOpen();
    });

    expect(result.current.connectionStatus).toBe("connected");
  });

  it("accumulates messages from SSE events", () => {
    const { result } = renderHook(() => useSSE("room-123"));

    act(() => {
      lastCreatedES?._emit(
        JSON.stringify({
          id: 1,
          room_id: "room-123",
          sender: "alice",
          content: "hello",
          message_type: "message",
          created_at: "2026-01-01T00:00:00Z",
          metadata: null,
        })
      );
    });

    expect(result.current.messages).toHaveLength(1);
    expect(result.current.messages[0].sender).toBe("alice");
  });

  it("clears messages on reset event", () => {
    const { result } = renderHook(() => useSSE("room-123"));

    // Add a message first
    act(() => {
      lastCreatedES?._emit(
        JSON.stringify({
          id: 1,
          room_id: "room-123",
          sender: "alice",
          content: "hello",
          message_type: "message",
          created_at: "2026-01-01T00:00:00Z",
          metadata: null,
        })
      );
    });
    expect(result.current.messages).toHaveLength(1);

    // Fire reset event
    act(() => {
      lastCreatedES?._emitNamed("reset");
    });
    expect(result.current.messages).toEqual([]);
  });

  it("clears messages on room change", () => {
    const { result, rerender } = renderHook(
      ({ roomId }) => useSSE(roomId),
      { initialProps: { roomId: "room-1" as string | null } }
    );

    act(() => {
      lastCreatedES?._emit(
        JSON.stringify({
          id: 1,
          room_id: "room-1",
          sender: "alice",
          content: "hello",
          message_type: "message",
          created_at: "2026-01-01T00:00:00Z",
          metadata: null,
        })
      );
    });
    expect(result.current.messages).toHaveLength(1);

    rerender({ roomId: "room-2" });
    expect(result.current.messages).toEqual([]);
  });

  it("sets connecting status on error (native reconnect)", () => {
    const { result } = renderHook(() => useSSE("room-123"));

    act(() => {
      lastCreatedES?._triggerError();
    });

    expect(result.current.connectionStatus).toBe("connecting");
    // Same EventSource — native reconnect, no new instance
    expect(lastCreatedES?.readyState).not.toBe(2);
  });

  it("does not create a new EventSource on error (relies on native reconnect)", () => {
    renderHook(() => useSSE("room-123"));
    const firstES = lastCreatedES;

    act(() => {
      firstES?._triggerError();
    });

    // Same instance — no new EventSource created
    expect(lastCreatedES).toBe(firstES);
  });

  it("does not schedule a retry timer on error", () => {
    vi.useFakeTimers();
    renderHook(() => useSSE("room-123"));
    const firstES = lastCreatedES;

    act(() => {
      firstES?._triggerError();
    });

    // Advance past old 3s retry delay — no new EventSource should appear
    act(() => {
      vi.advanceTimersByTime(5000);
    });

    expect(lastCreatedES).toBe(firstES);
  });

  it("preserves messages across native reconnect", () => {
    const { result } = renderHook(() => useSSE("room-123"));

    act(() => {
      lastCreatedES?._emit(
        JSON.stringify({
          id: 1,
          room_id: "room-123",
          sender: "alice",
          content: "hello",
          message_type: "message",
          created_at: "2026-01-01T00:00:00Z",
          metadata: null,
        })
      );
    });
    expect(result.current.messages).toHaveLength(1);

    // Simulate error — native reconnect, ES stays open
    act(() => {
      lastCreatedES?._triggerError();
    });
    expect(result.current.connectionStatus).toBe("connecting");

    // On reconnect, onopen fires again
    act(() => {
      lastCreatedES?._triggerOpen();
    });
    expect(result.current.connectionStatus).toBe("connected");
    expect(result.current.messages).toHaveLength(1);
    expect(result.current.messages[0].content).toBe("hello");
  });

  it("closes the old EventSource on room change", () => {
    const { rerender } = renderHook(
      ({ roomId }) => useSSE(roomId),
      { initialProps: { roomId: "room-1" as string | null } }
    );

    const firstES = lastCreatedES!;
    expect(firstES.readyState).not.toBe(2);

    // Change rooms — old ES should be closed
    rerender({ roomId: "room-2" });
    expect(firstES.readyState).toBe(2);
    expect(lastCreatedES).not.toBe(firstES);
  });

  it("closes the EventSource on unmount", () => {
    const { unmount } = renderHook(() => useSSE("room-123"));
    const es = lastCreatedES!;
    expect(es.readyState).not.toBe(2);

    unmount();
    expect(es.readyState).toBe(2);
  });

  it("closes EventSource on unmount preventing native reconnect", () => {
    const { unmount } = renderHook(() => useSSE("room-123"));
    const es = lastCreatedES!;
    expect(es.readyState).not.toBe(2);

    unmount();
    expect(es.readyState).toBe(2); // CLOSED — native reconnect won't fire
  });

  it("handles malformed JSON without crashing", () => {
    const { result } = renderHook(() => useSSE("room-123"));
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});

    act(() => {
      lastCreatedES?._triggerOpen();
    });

    // Emit invalid JSON — should not throw or add messages
    act(() => {
      lastCreatedES?._emit("not json");
    });

    expect(result.current.messages).toEqual([]);
    expect(result.current.connectionStatus).toBe("connected");
    expect(warnSpy).toHaveBeenCalledWith("useSSE: failed to parse message JSON");
    warnSpy.mockRestore();
  });
});
