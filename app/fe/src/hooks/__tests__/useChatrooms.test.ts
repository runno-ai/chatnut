import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useChatrooms } from "../useChatrooms";
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
});

describe("useChatrooms", () => {
  it("starts in loading state", () => {
    const { result } = renderHook(() => useChatrooms());
    expect(result.current.loading).toBe(true);
    expect(result.current.active).toEqual([]);
    expect(result.current.archived).toEqual([]);
  });

  it("connects to SSE with project filter", () => {
    renderHook(() => useChatrooms("my-project"));
    expect(lastCreatedES?.url).toContain("project=my-project");
  });

  it("connects without filter when no project", () => {
    renderHook(() => useChatrooms());
    expect(lastCreatedES?.url).not.toContain("project=");
  });

  it("parses SSE data into active and archived rooms", () => {
    const { result } = renderHook(() => useChatrooms());

    act(() => {
      lastCreatedES?._emit(
        JSON.stringify({
          active: [
            { id: "1", name: "dev", project: "proj", status: "live", messageCount: 5 },
          ],
          archived: [
            { id: "2", name: "old", project: "proj", status: "archived" },
          ],
        })
      );
    });

    expect(result.current.loading).toBe(false);
    expect(result.current.active).toHaveLength(1);
    expect(result.current.active[0].name).toBe("dev");
    expect(result.current.archived).toHaveLength(1);
  });

  it("resets state when project changes", () => {
    const { result, rerender } = renderHook(
      ({ project }) => useChatrooms(project),
      { initialProps: { project: "proj-a" as string | undefined } }
    );

    rerender({ project: "proj-b" });
    expect(result.current.loading).toBe(true);
    expect(result.current.active).toEqual([]);
  });

  it("retries connection on error", () => {
    vi.useFakeTimers();
    renderHook(() => useChatrooms());
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
    vi.useRealTimers();
  });
});
