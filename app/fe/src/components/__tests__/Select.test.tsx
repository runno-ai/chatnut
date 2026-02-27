import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import { Select } from "../Select";

afterEach(() => {
  cleanup();
});

const options = [
  { value: "a", label: "Alpha" },
  { value: "b", label: "Beta" },
];

function renderSelect(overrides: Partial<Parameters<typeof Select>[0]> = {}) {
  const onChange = vi.fn();
  const utils = render(
    <Select
      value=""
      onChange={onChange}
      options={options}
      placeholder="Pick one"
      {...overrides}
    />
  );
  return { ...utils, onChange };
}

describe("Select", () => {
  it("renders with placeholder text when no value selected", () => {
    renderSelect();
    expect(screen.getByText("Pick one")).toBeTruthy();
  });

  it("renders selected option label", () => {
    renderSelect({ value: "a" });
    expect(screen.getByText("Alpha")).toBeTruthy();
  });

  it("opens dropdown on click and shows options", () => {
    renderSelect();
    const trigger = screen.getByRole("button", { name: /pick one/i });
    fireEvent.click(trigger);
    // Dropdown should show placeholder + 2 options
    expect(screen.getByText("Alpha")).toBeTruthy();
    expect(screen.getByText("Beta")).toBeTruthy();
  });

  it("calls onChange when option is clicked", () => {
    const { onChange } = renderSelect();
    const trigger = screen.getByRole("button", { name: /pick one/i });
    fireEvent.click(trigger);
    fireEvent.click(screen.getByText("Beta"));
    expect(onChange).toHaveBeenCalledWith("b");
  });

  it("clears value when placeholder option is clicked in dropdown", () => {
    const { onChange } = renderSelect({ value: "a" });
    const trigger = screen.getByRole("button", { name: /alpha/i });
    fireEvent.click(trigger);
    // Find the "Pick one" option in the dropdown (not the trigger)
    const dropdownOptions = screen.getAllByText("Pick one");
    // Click the dropdown one (last one, since trigger is now showing "Alpha")
    fireEvent.click(dropdownOptions[0]);
    expect(onChange).toHaveBeenCalledWith("");
  });

  it("closes dropdown on Escape key", () => {
    renderSelect();
    const trigger = screen.getByRole("button", { name: /pick one/i });
    fireEvent.click(trigger);
    // Dropdown is open — options visible
    expect(screen.getByText("Alpha")).toBeTruthy();
    fireEvent.keyDown(trigger, { key: "Escape" });
    // Dropdown is closed — only trigger button remains
    expect(screen.getAllByRole("button")).toHaveLength(1);
  });

  it("closes dropdown on outside click", () => {
    renderSelect();
    const trigger = screen.getByRole("button", { name: /pick one/i });
    fireEvent.click(trigger);
    expect(screen.getByText("Alpha")).toBeTruthy();
    fireEvent.mouseDown(document.body);
    expect(screen.getAllByRole("button")).toHaveLength(1);
  });

  it("has correct ARIA attributes", () => {
    renderSelect();
    const trigger = screen.getByRole("button", { name: /pick one/i });
    expect(trigger.getAttribute("aria-haspopup")).toBe("listbox");
    expect(trigger.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(trigger);
    expect(trigger.getAttribute("aria-expanded")).toBe("true");
  });

  it("does not open when disabled", () => {
    renderSelect({ disabled: true });
    const buttons = screen.getAllByRole("button");
    expect(buttons).toHaveLength(1);
    const trigger = buttons[0];
    expect(trigger.hasAttribute("disabled")).toBe(true);
    fireEvent.click(trigger);
    // Should still only have 1 button (no dropdown)
    expect(screen.getAllByRole("button")).toHaveLength(1);
  });

  it("renders custom icon", () => {
    renderSelect({ icon: <span data-testid="custom-icon">!</span> });
    expect(screen.getByTestId("custom-icon")).toBeTruthy();
  });
});
