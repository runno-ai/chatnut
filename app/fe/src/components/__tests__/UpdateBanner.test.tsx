import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { UpdateBanner } from "../UpdateBanner";

afterEach(() => {
  cleanup();
});

describe("UpdateBanner", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("renders banner when update is available", () => {
    render(<UpdateBanner info={{ version: "0.2.0", latest: "0.3.0", update_available: true }} />);
    expect(screen.getByRole("status")).toBeTruthy();
    expect(screen.getByText(/v0\.3\.0 available/)).toBeTruthy();
  });

  it("returns null when no update available", () => {
    const { container } = render(
      <UpdateBanner info={{ version: "0.3.0", latest: "0.3.0", update_available: false }} />
    );
    expect(container.innerHTML).toBe("");
  });

  it("returns null when update_available is undefined", () => {
    const { container } = render(
      <UpdateBanner info={{ version: "0.3.0" }} />
    );
    expect(container.innerHTML).toBe("");
  });

  it("dismisses on button click", () => {
    render(<UpdateBanner info={{ version: "0.2.0", latest: "0.3.0", update_available: true }} />);
    fireEvent.click(screen.getByLabelText("Dismiss update notification"));
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("persists dismissal in localStorage", () => {
    render(<UpdateBanner info={{ version: "0.2.0", latest: "0.3.0", update_available: true }} />);
    fireEvent.click(screen.getByLabelText("Dismiss update notification"));
    expect(localStorage.getItem("tc:update-dismissed:0.3.0")).toBe("1");
  });

  it("stays dismissed after re-render with same version", () => {
    localStorage.setItem("tc:update-dismissed:0.3.0", "1");
    const { container } = render(
      <UpdateBanner info={{ version: "0.2.0", latest: "0.3.0", update_available: true }} />
    );
    expect(container.querySelector("[role=status]")).toBeNull();
  });
});
