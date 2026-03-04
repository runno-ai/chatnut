import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useStatus } from "../useStatus";
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
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("useStatus", () => {
  it("returns empty statuses when roomId is null", () => {
    const { result } = renderHook(() => useStatus(null));
    expect(result.current).toEqual([]);
    expect(lastCreatedES).toBeNull();
  });

  it("connects to SSE endpoint with room ID", () => {
    renderHook(() => useStatus("room-123"));
    expect(lastCreatedES).not.toBeNull();
    expect(lastCreatedES?.url).toContain(
      "/api/stream/status?room_id=room-123"
    );
  });

  it("encodes room ID in URL", () => {
    renderHook(() => useStatus("room with spaces"));
    expect(lastCreatedES?.url).toContain(
      "room_id=room%20with%20spaces"
    );
  });

  it("parses SSE status data into state", () => {
    const { result } = renderHook(() => useStatus("room-123"));

    act(() => {
      lastCreatedES?._emit(
        JSON.stringify({
          statuses: [
            {
              sender: "alice",
              status: "working on tests",
              updated_at: "2026-01-01T00:00:00Z",
            },
            {
              sender: "bob",
              status: "reviewing PR",
              updated_at: "2026-01-01T00:01:00Z",
            },
          ],
        })
      );
    });

    expect(result.current).toHaveLength(2);
    expect(result.current[0].sender).toBe("alice");
    expect(result.current[0].status).toBe("working on tests");
    expect(result.current[1].sender).toBe("bob");
  });

  it("updates state when new SSE data arrives", () => {
    const { result } = renderHook(() => useStatus("room-123"));

    act(() => {
      lastCreatedES?._emit(
        JSON.stringify({
          statuses: [
            { sender: "alice", status: "idle", updated_at: "2026-01-01T00:00:00Z" },
          ],
        })
      );
    });

    expect(result.current).toHaveLength(1);
    expect(result.current[0].status).toBe("idle");

    act(() => {
      lastCreatedES?._emit(
        JSON.stringify({
          statuses: [
            { sender: "alice", status: "coding", updated_at: "2026-01-01T00:01:00Z" },
            { sender: "bob", status: "testing", updated_at: "2026-01-01T00:01:00Z" },
          ],
        })
      );
    });

    expect(result.current).toHaveLength(2);
    expect(result.current[0].status).toBe("coding");
  });

  it("ignores SSE data without statuses array", () => {
    const { result } = renderHook(() => useStatus("room-123"));

    act(() => {
      lastCreatedES?._emit(JSON.stringify({ something: "else" }));
    });

    expect(result.current).toEqual([]);
  });

  it("retries connection on error", () => {
    vi.useFakeTimers();
    renderHook(() => useStatus("room-123"));
    const firstES = lastCreatedES;

    act(() => {
      firstES?._triggerError();
    });

    // Advance past the 3-second retry delay
    act(() => {
      vi.advanceTimersByTime(3000);
    });

    // A new EventSource should have been created
    expect(lastCreatedES).not.toBe(firstES);
  });

  it("closes old EventSource on error before reconnecting", () => {
    vi.useFakeTimers();
    renderHook(() => useStatus("room-123"));
    const firstES = lastCreatedES!;

    act(() => {
      firstES._triggerError();
    });

    expect(firstES.readyState).toBe(2); // closed
  });

  it("resets statuses and reconnects when roomId changes", () => {
    const { result, rerender } = renderHook(
      ({ roomId }) => useStatus(roomId),
      { initialProps: { roomId: "room-1" as string | null } }
    );
    const firstES = lastCreatedES!;

    // Add some status data
    act(() => {
      lastCreatedES?._emit(
        JSON.stringify({
          statuses: [
            { sender: "alice", status: "working", updated_at: "2026-01-01T00:00:00Z" },
          ],
        })
      );
    });
    expect(result.current).toHaveLength(1);

    // Change room
    rerender({ roomId: "room-2" });

    // Old ES should be closed
    expect(firstES.readyState).toBe(2);
    // Statuses should be reset
    expect(result.current).toEqual([]);
    // A new ES should be created
    expect(lastCreatedES).not.toBe(firstES);
    expect(lastCreatedES?.url).toContain("room_id=room-2");
  });

  it("clears statuses when roomId changes to null", () => {
    const { result, rerender } = renderHook(
      ({ roomId }) => useStatus(roomId),
      { initialProps: { roomId: "room-1" as string | null } }
    );

    act(() => {
      lastCreatedES?._emit(
        JSON.stringify({
          statuses: [
            { sender: "alice", status: "working", updated_at: "2026-01-01T00:00:00Z" },
          ],
        })
      );
    });
    expect(result.current).toHaveLength(1);

    const esBeforeNull = lastCreatedES!;
    rerender({ roomId: null });

    expect(esBeforeNull.readyState).toBe(2);
    expect(result.current).toEqual([]);
  });

  it("closes the EventSource on unmount", () => {
    const { unmount } = renderHook(() => useStatus("room-123"));
    const es = lastCreatedES!;
    expect(es.readyState).not.toBe(2);

    unmount();
    expect(es.readyState).toBe(2);
  });

  it("does not reconnect after unmount when retry is pending", () => {
    vi.useFakeTimers();
    const { unmount } = renderHook(() => useStatus("room-123"));
    const firstES = lastCreatedES!;

    act(() => {
      firstES._triggerError(); // schedules retry
    });

    unmount(); // should clear retry timer

    const beforeAdvance = lastCreatedES;
    act(() => {
      vi.advanceTimersByTime(3000);
    });

    expect(lastCreatedES).toBe(beforeAdvance); // no new EventSource
  });

  it("handles malformed JSON without crashing", () => {
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    const { result } = renderHook(() => useStatus("room-123"));

    act(() => {
      lastCreatedES?._emit("not json");
    });

    expect(result.current).toEqual([]);
    expect(warnSpy).toHaveBeenCalledWith(
      "useStatus: failed to parse status JSON"
    );
    warnSpy.mockRestore();
  });
});
