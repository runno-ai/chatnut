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

  it("sets connecting status on error and retries", () => {
    vi.useFakeTimers();
    const { result } = renderHook(() => useSSE("room-123"));
    const firstES = lastCreatedES;

    act(() => {
      firstES?._triggerError();
    });

    expect(result.current.connectionStatus).toBe("connecting");

    // Advance past the 3-second retry delay
    act(() => {
      vi.advanceTimersByTime(3000);
    });

    // A new EventSource should have been created
    expect(lastCreatedES).not.toBe(firstES);
    vi.useRealTimers();
  });
});
