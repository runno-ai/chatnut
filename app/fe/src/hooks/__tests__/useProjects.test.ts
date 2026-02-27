import { describe, it, expect, vi, afterEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { useProjects } from "../useProjects";

afterEach(() => {
  vi.restoreAllMocks();
});

function mockFetch(data: unknown, ok = true, status = 200) {
  return vi.spyOn(globalThis, "fetch").mockResolvedValue({
    ok,
    status,
    json: () => Promise.resolve(data),
  } as Response);
}

describe("useProjects", () => {
  it("starts with empty array", () => {
    mockFetch([]);
    const { result } = renderHook(() => useProjects());
    expect(result.current).toEqual([]);
  });

  it("fetches and returns project list from array response", async () => {
    mockFetch(["proj-a", "proj-b"]);
    const { result } = renderHook(() => useProjects());
    await waitFor(() => expect(result.current).toEqual(["proj-a", "proj-b"]));
  });

  it("handles wrapped response with projects key", async () => {
    mockFetch({ projects: ["alpha", "beta"] });
    const { result } = renderHook(() => useProjects());
    await waitFor(() => expect(result.current).toEqual(["alpha", "beta"]));
  });

  it("filters out non-string values", async () => {
    mockFetch(["valid", 123, null, "also-valid"]);
    const { result } = renderHook(() => useProjects());
    await waitFor(() => expect(result.current).toEqual(["valid", "also-valid"]));
  });

  it("handles non-ok response gracefully", async () => {
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    mockFetch(null, false, 500);
    const { result } = renderHook(() => useProjects());
    // Wait for the fetch cycle to complete
    await waitFor(() => expect(warnSpy).toHaveBeenCalled());
    expect(result.current).toEqual([]);
    warnSpy.mockRestore();
  });

  it("handles unexpected payload shape", async () => {
    const spy = mockFetch({ something: "else" });
    const { result } = renderHook(() => useProjects());
    // Wait for fetch to actually complete before asserting
    await waitFor(() => expect(spy).toHaveBeenCalled());
    expect(result.current).toEqual([]);
  });

  it("handles network failure gracefully", async () => {
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new TypeError("Failed to fetch"));
    const { result } = renderHook(() => useProjects());
    await waitFor(() => expect(warnSpy).toHaveBeenCalledWith("Failed to fetch projects:", expect.any(TypeError)));
    expect(result.current).toEqual([]);
    warnSpy.mockRestore();
  });

  it("aborts fetch on unmount", () => {
    const abortSpy = vi.spyOn(AbortController.prototype, "abort");
    mockFetch(["a"]);
    const { unmount } = renderHook(() => useProjects());
    unmount();
    expect(abortSpy).toHaveBeenCalled();
  });
});
