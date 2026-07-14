import { fireEvent, render, screen } from "@testing-library/react";
import type { CustomerPreferences as CustomerPreferencesData } from "@/lib/gateway/types";
import { CustomerPreferences } from "./CustomerPreferences";

function renderPreferences(preferences: CustomerPreferencesData = {}) {
  const handlers = { onUpsert: vi.fn(), onClear: vi.fn() };
  render(<CustomerPreferences preferences={preferences} {...handlers} />);
  return handlers;
}

describe("CustomerPreferences", () => {
  it("shows all 4 slots with human labels and values, empty ones as Not set", () => {
    renderPreferences({
      contact_time_preference: "Evenings after 6pm",
      channel_preference: "sms",
    });
    expect(screen.getByText("Preferred contact time")).toBeInTheDocument();
    expect(screen.getByText("Evenings after 6pm")).toBeInTheDocument();
    expect(screen.getByText("Preferred channel")).toBeInTheDocument();
    expect(screen.getByText("sms")).toBeInTheDocument();
    expect(screen.getByText("Delivery habit note")).toBeInTheDocument();
    expect(screen.getByText("Communication style")).toBeInTheDocument();
    expect(screen.getAllByText("Not set")).toHaveLength(2);
  });

  it("edits an unset slot inline and fires onUpsert with the trimmed value", () => {
    const h = renderPreferences({});
    fireEvent.click(screen.getByRole("button", { name: /edit preferred channel/i }));
    fireEvent.change(screen.getByLabelText("Preferred channel"), {
      target: { value: "  email  " },
    });
    fireEvent.click(screen.getByRole("button", { name: /^save$/i }));
    expect(h.onUpsert).toHaveBeenCalledWith("channel_preference", "email");
  });

  it("cancels an edit without calling onUpsert", () => {
    const h = renderPreferences({ contact_time_preference: "Evenings" });
    fireEvent.click(screen.getByRole("button", { name: /edit preferred contact time/i }));
    fireEvent.change(screen.getByLabelText("Preferred contact time"), {
      target: { value: "Mornings" },
    });
    fireEvent.click(screen.getByRole("button", { name: /^cancel$/i }));
    expect(h.onUpsert).not.toHaveBeenCalled();
    expect(screen.getByText("Evenings")).toBeInTheDocument();
  });

  it("requires an explicit confirm step before clearing a set slot", () => {
    const h = renderPreferences({ delivery_habit_note: "Leave at back door" });
    fireEvent.click(screen.getByRole("button", { name: /clear delivery habit note/i }));
    expect(h.onClear).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: /confirm clear/i }));
    expect(h.onClear).toHaveBeenCalledWith("delivery_habit_note");
  });

  it("cancels a pending clear without calling onClear", () => {
    const h = renderPreferences({ delivery_habit_note: "Leave at back door" });
    fireEvent.click(screen.getByRole("button", { name: /clear delivery habit note/i }));
    fireEvent.click(screen.getByRole("button", { name: /^cancel$/i }));
    expect(h.onClear).not.toHaveBeenCalled();
    expect(screen.getByText("Leave at back door")).toBeInTheDocument();
  });

  it("hides the clear control for a slot that has no value", () => {
    renderPreferences({});
    expect(screen.queryByRole("button", { name: /clear preferred channel/i })).toBeNull();
  });
});
