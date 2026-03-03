import { renderHook, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { useVersion } from "../useVersion";

describe("useVersion", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("fetches version info from /api/status", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        status: "ok",
        version: "0.2.0",
        latest: "0.3.0",
        update_available: true,
      }),
    } as Response);

    const { result } = renderHook(() => useVersion());
    await waitFor(() => expect(result.current).not.toBeNull());
    expect(result.current?.version).toBe("0.2.0");
    expect(result.current?.latest).toBe("0.3.0");
    expect(result.current?.update_available).toBe(true);
  });

  it("returns null on fetch failure", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValueOnce(new Error("network"));
    const { result } = renderHook(() => useVersion());
    await waitFor(
      () => {
        expect(result.current).toBeNull();
      },
      { timeout: 200 },
    );
  });
});
