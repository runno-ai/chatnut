# MCP-24: Frontend SSE Reliability Implementation Plan

## Context

The chatnut frontend's `useSSE` hook creates a new `EventSource` on reconnection without tracking the last received event ID, causing message loss or full replay on disconnect. Additionally, the Vite dev proxy hardcodes port 8000, which breaks when the portless dev server binds to a dynamic port. Tests for useSSE already exist and are comprehensive — only new tests for the reconnection feature are needed.

## Goal

Fix SSE reconnection to preserve message continuity via `Last-Event-Id` tracking, and make the Vite dev proxy port configurable.

## Architecture

The backend sends SSE `id:` fields (message DB IDs) and honors the `Last-Event-Id` HTTP header on the `GET /api/stream/messages` endpoint. The current frontend bug: the `onerror` handler manually closes the EventSource and creates a new one after 3s, **bypassing the browser's native auto-reconnect** which would automatically send `Last-Event-Id` on reconnection. The fix: stop manually closing/recreating EventSource on error — let the browser handle reconnection natively. This requires zero backend changes. The Vite proxy fix reads `CHATNUT_DEV_PORT` from `process.env` with fallback to `8000`.

## Affected Areas

- Frontend: `app/fe/src/hooks/useSSE.ts`, `app/fe/src/hooks/__tests__/useSSE.test.ts`, `app/fe/vite.config.ts`

## Key Files

- `app/fe/src/hooks/useSSE.ts` — Core hook to modify (add Last-Event-Id tracking)
- `app/fe/src/hooks/__tests__/useSSE.test.ts` — Existing test suite to extend
- `app/fe/src/hooks/__tests__/helpers.ts` — MockEventSource (needs `lastEventId` support)
- `app/fe/vite.config.ts` — Dev proxy port config
- `app/be/chatnut/routes.py:266-281` — Backend SSE endpoint (reference — confirms `Last-Event-Id` header support, no changes needed)

## Reusable Utilities

- `MockEventSource` in `app/fe/src/hooks/__tests__/helpers.ts` — existing mock for SSE tests; needs extension to simulate native auto-reconnect behavior
- Backend `stream_messages` endpoint already honors `Last-Event-Id` header — the browser's native EventSource reconnect sends this automatically

---

## Tasks

### Task 1: Switch useSSE to native EventSource auto-reconnect

**Files:**
- Modify: `app/fe/src/hooks/useSSE.ts`
- Modify: `app/fe/src/hooks/__tests__/helpers.ts`
- Modify: `app/fe/src/hooks/__tests__/useSSE.test.ts`

**Step 1: Write the failing tests**

First, update `MockEventSource._triggerError()` in `helpers.ts` to accept an optional `readyState` parameter (default: 0 for native reconnect behavior, pass 2 for explicit-close scenarios). This avoids a global behavior change that could break other test suites:

```typescript
_triggerError(readyState: number = 0) {
  // Default: native EventSource sets CONNECTING (0) on error (browser auto-reconnects)
  // Pass 2 (CLOSED) for explicit-close test scenarios
  this.readyState = readyState;
  const event = new Event("error");
  this.onerror?.(event);
  for (const listener of this.listeners["error"] ?? []) {
    listener(event);
  }
}
```

Then add tests to `useSSE.test.ts`:

```typescript
it("preserves messages across native reconnect (no duplicate fetch)", () => {
  const { result } = renderHook(() => useSSE("room-123"));

  // Receive a message
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

  // Simulate error — should NOT close the EventSource (native reconnect)
  act(() => {
    lastCreatedES?._triggerError();
  });

  // Status should be "connecting" (not "disconnected")
  expect(result.current.connectionStatus).toBe("connecting");

  // The SAME EventSource instance should still be active (not closed/replaced)
  expect(lastCreatedES?.readyState).not.toBe(2);

  // On reconnect, onopen fires again
  act(() => {
    lastCreatedES?._triggerOpen();
  });
  expect(result.current.connectionStatus).toBe("connected");

  // Original messages are preserved
  expect(result.current.messages).toHaveLength(1);
  expect(result.current.messages[0].content).toBe("hello");
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
```

**Step 2: Run test — expect FAIL**
```bash
cd app/fe && bun run test
```
Expected: tests fail because `useSSE.ts` still manually closes and recreates EventSource on error.

**Step 3: Implement minimal code**

In `useSSE.ts`, simplify the `onerror` handler to NOT close the EventSource — let the browser's native auto-reconnect handle it. The browser will automatically send `Last-Event-Id` header on reconnect, which the backend already honors.

Replace the current `onerror` handler:
```typescript
// BEFORE (manual close + recreate — bypasses native reconnect):
es.onerror = () => {
  es.close();
  esRef.current = null;
  if (closed) {
    setConnectionStatus("disconnected");
  } else {
    setConnectionStatus("connecting");
    retryRef.current = setTimeout(connect, 3000);
  }
};

// AFTER (native reconnect — browser handles retry + Last-Event-Id):
es.onerror = () => {
  if (closed) {
    es.close();
    esRef.current = null;
    setConnectionStatus("disconnected");
  } else {
    setConnectionStatus("connecting");
    // Don't close — browser auto-reconnects and sends Last-Event-Id header
  }
};
```

Also remove the `retryRef` since manual retry is no longer needed:
- Remove `const retryRef = useRef<ReturnType<typeof setTimeout> | null>(null);`
- Remove `if (retryRef.current) clearTimeout(retryRef.current);` from cleanup
- Remove `retryRef.current = null;` from cleanup

The cleanup function still calls `es.close()` (which sets `closed = true` first, so the `onerror` handler knows to not reconnect).

Note: `MockEventSource._triggerError()` was already updated in Step 1 (helpers.ts) with an optional `readyState` parameter (defaults to 0 for native reconnect).

Add a browser compatibility comment to the new `onerror` handler:
```typescript
// Native EventSource auto-reconnect: browser retries with Last-Event-Id header.
// Supported in all modern browsers (Chrome, Firefox, Safari, Edge).
// Reconnect interval is browser-default (~3s) unless server sends SSE retry: field.
```

**Step 4: Run test — expect PASS**
```bash
cd app/fe && bun run test
```

**Step 5: Update existing tests that assumed manual reconnect**

The existing test "sets connecting status on error and retries" expects a NEW EventSource after error + 3s timeout. Update it to expect the SAME EventSource (native reconnect):

```typescript
it("sets connecting status on error (native reconnect)", () => {
  const { result } = renderHook(() => useSSE("room-123"));

  act(() => {
    lastCreatedES?._triggerError();
  });

  expect(result.current.connectionStatus).toBe("connecting");
  // Same EventSource — native reconnect, no new instance
});
```

The "does not reconnect after unmount when retry is pending" test should verify that unmount closes the ES so native reconnect stops:

```typescript
it("closes EventSource on unmount preventing native reconnect", () => {
  const { unmount } = renderHook(() => useSSE("room-123"));
  const es = lastCreatedES!;

  unmount();
  expect(es.readyState).toBe(2); // CLOSED — native reconnect won't fire
});
```

**Step 6: Commit**
```bash
git add app/fe/src/hooks/useSSE.ts app/fe/src/hooks/__tests__/useSSE.test.ts app/fe/src/hooks/__tests__/helpers.ts
git commit -m "fix(fe): use native EventSource reconnect for Last-Event-Id continuity (MCP-24)"
```

---

### Task 2: Make Vite dev proxy port configurable

**Files:**
- Modify: `app/fe/vite.config.ts`

**Step 1: Write the failing test**

No unit test applicable — this is build config. Verified manually and via CI build.

**Step 2: Implement**

In `vite.config.ts`, replace the hardcoded proxy target:

```typescript
const devPort = process.env.CHATNUT_DEV_PORT || "8000";
const devTarget = `http://localhost:${devPort}`;

export default defineConfig({
  server: {
    port: 5173,
    proxy: {
      "/api": devTarget,
      "/mcp": devTarget,
    },
  },
  // ... rest unchanged
});
```

**Step 3: Commit**
```bash
git add app/fe/vite.config.ts
git commit -m "fix(fe): read CHATNUT_DEV_PORT for Vite dev proxy target (MCP-24)"
```

---

### Task 3: Documentation Update

- [ ] Update `CLAUDE.md` environment variables table with `CHATNUT_DEV_PORT`
- [ ] Add inline comment in `vite.config.ts` explaining the env var

---

## Verification

```bash
cd app/fe && bun run test
cd app/fe && npx tsc --noEmit
cd app/fe && bun run build
```

Expected: All frontend tests pass (including new native-reconnect tests), TypeScript compiles cleanly, production build succeeds. No backend changes needed.

## AI Review Findings

### Round 1 (Domain Team)

| Severity | Source | Finding | Action |
|----------|--------|---------|--------|
| Critical | Architect + Frontend Dev | Backend `stream_messages` endpoint does NOT accept `since_id` query param — only `Last-Event-Id` header. Original plan's manual reconnect + query param approach would silently fail. | **Restructured**: switched to native EventSource auto-reconnect. Browser automatically sends `Last-Event-Id` header. Zero backend changes needed. |
| Warning | Architect | Env var `CHATNUT_DEV_PORT` naming could be clearer (it's the proxy target, not the dev server port). | Kept `CHATNUT_DEV_PORT` — matches the portless convention and is documented in CLAUDE.md. |
| Suggestion | Frontend Dev | Native reconnect approach is simpler (fewer refs, no manual retry timer, browser handles backoff). | Adopted — plan restructured around native reconnect. |

### Round 2 (MiniMax + Codex + Gemini)

| Severity | Source | Finding | Action |
|----------|--------|---------|--------|
| Warning | Codex | `_triggerError` readyState=0 is a global change affecting all test suites using MockEventSource. | **Fixed**: made `_triggerError` accept optional `readyState` param (default 0, pass 2 for close scenarios). |
| Warning | Codex | Missing fake-timer test to verify no setTimeout scheduled after error. | **Added**: new test "does not schedule a retry timer on error" with vi.advanceTimersByTime(5000). |
| Warning | Gemini | `_simulateReconnect()` stub is a no-op. | **Removed**: tests use `_triggerError()` + `_triggerOpen()` directly instead. |
| Warning | MiniMax + Gemini | Browser reconnect timing depends on server `retry:` field (browser default ~3s if absent). | **Documented**: added browser compat comment in onerror handler. Accepted trade-off — backend doesn't send retry field, browser default is acceptable. |
| Warning | Gemini | Plan should note why "closes old ES on room change" test is safe (uses es.close() directly, not _triggerError). | Noted: that test calls cleanup which calls es.close() — unaffected by _triggerError change. |
| Suggestion | MiniMax | Hybrid approach: native reconnect + fallback timer. | Deferred — native-only is sufficient for current use case. |
| Suggestion | Codex | Vite `process.env` only picks up shell-exported vars, not .env files. | Accepted — portless dev start script exports the var. Documented. |
| Suggestion | Gemini | Merge overlapping "same instance" tests. | Kept separate — each tests a distinct invariant (same instance vs no timer). |
