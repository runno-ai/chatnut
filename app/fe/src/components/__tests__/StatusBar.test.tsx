import { render, screen, cleanup } from "@testing-library/react";
import { describe, it, expect, afterEach, vi, beforeEach, afterAll } from "vitest";
import { StatusBar } from "../StatusBar";

afterEach(() => {
  cleanup();
});

function nowIso(): string {
  return new Date().toISOString();
}

function staleIso(): string {
  // 10 minutes ago — past the 5-minute STALE_MS threshold
  return new Date(Date.now() - 10 * 60 * 1000).toISOString();
}

describe("StatusBar", () => {
  it("renders nothing when statuses is empty", () => {
    const { container } = render(<StatusBar statuses={[]} />);
    expect(container.firstChild).toBeNull();
  });

  it("renders sender names", () => {
    render(
      <StatusBar
        statuses={[
          { sender: "alice", status: "working on task", updated_at: nowIso() },
          { sender: "bob", status: "reviewing PR", updated_at: nowIso() },
        ]}
      />
    );
    expect(screen.getByText("alice")).toBeTruthy();
    expect(screen.getByText("bob")).toBeTruthy();
  });

  it("renders status text", () => {
    render(
      <StatusBar
        statuses={[
          { sender: "alice", status: "working on task", updated_at: nowIso() },
        ]}
      />
    );
    expect(screen.getByText("working on task")).toBeTruthy();
  });

  it("renders multiple statuses", () => {
    render(
      <StatusBar
        statuses={[
          { sender: "alice", status: "idle", updated_at: nowIso() },
          { sender: "bob", status: "blocked on review", updated_at: nowIso() },
          { sender: "charlie", status: "done", updated_at: nowIso() },
        ]}
      />
    );
    expect(screen.getByText("alice")).toBeTruthy();
    expect(screen.getByText("bob")).toBeTruthy();
    expect(screen.getByText("charlie")).toBeTruthy();
    expect(screen.getByText("idle")).toBeTruthy();
    expect(screen.getByText("blocked on review")).toBeTruthy();
    expect(screen.getByText("done")).toBeTruthy();
  });

  it("shows 'now' for recent timestamps", () => {
    render(
      <StatusBar
        statuses={[
          { sender: "alice", status: "working", updated_at: nowIso() },
        ]}
      />
    );
    expect(screen.getByText("now")).toBeTruthy();
  });

  it("applies yellow color class for blocked status", () => {
    const { container } = render(
      <StatusBar
        statuses={[
          { sender: "alice", status: "blocked on PR", updated_at: nowIso() },
        ]}
      />
    );
    // The status text span should have a yellow color class
    const statusSpan = container.querySelector(".text-yellow-500");
    expect(statusSpan).toBeTruthy();
  });

  it("applies green color class for active non-blocked status", () => {
    const { container } = render(
      <StatusBar
        statuses={[
          { sender: "alice", status: "working on task", updated_at: nowIso() },
        ]}
      />
    );
    const statusSpan = container.querySelector(".text-green-400");
    expect(statusSpan).toBeTruthy();
  });

  it("applies gray color class for stale status", () => {
    const { container } = render(
      <StatusBar
        statuses={[
          { sender: "alice", status: "working on task", updated_at: staleIso() },
        ]}
      />
    );
    const statusSpan = container.querySelector(".text-gray-500");
    expect(statusSpan).toBeTruthy();
  });
});
