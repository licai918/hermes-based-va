import { fireEvent, render, screen } from "@testing-library/react";
import type { DraftProposal } from "@/lib/api/copilot-client";
import { PendingProposals } from "./PendingProposals";

function renderProposals(proposals: DraftProposal[]) {
  const handlers = { onAccept: vi.fn(), onDismiss: vi.fn() };
  render(<PendingProposals proposals={proposals} {...handlers} />);
  return handlers;
}

describe("PendingProposals", () => {
  it("renders nothing when there are no pending proposals", () => {
    const { container } = render(
      <PendingProposals proposals={[]} onAccept={vi.fn()} onDismiss={vi.fn()} />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("shows each proposal as a suggested slot = value with Accept/Dismiss", () => {
    renderProposals([
      { slot: "contact_time_preference", value: "Evenings after 6pm", evidenceTurn: "text me after 6" },
    ]);
    expect(
      screen.getByText('Suggest setting Preferred contact time = "Evenings after 6pm"'),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /accept preferred contact time proposal/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /dismiss preferred contact time proposal/i })).toBeInTheDocument();
  });

  it("fires onAccept with the full proposal", () => {
    const h = renderProposals([{ slot: "channel_preference", value: "sms" }]);
    fireEvent.click(screen.getByRole("button", { name: /accept preferred channel proposal/i }));
    expect(h.onAccept).toHaveBeenCalledWith({ slot: "channel_preference", value: "sms" });
    expect(h.onDismiss).not.toHaveBeenCalled();
  });

  it("fires onDismiss with the full proposal", () => {
    const h = renderProposals([{ slot: "channel_preference", value: "sms" }]);
    fireEvent.click(screen.getByRole("button", { name: /dismiss preferred channel proposal/i }));
    expect(h.onDismiss).toHaveBeenCalledWith({ slot: "channel_preference", value: "sms" });
    expect(h.onAccept).not.toHaveBeenCalled();
  });

  it("renders multiple pending proposals", () => {
    renderProposals([
      { slot: "channel_preference", value: "sms" },
      { slot: "delivery_habit_note", value: "Leave at back door" },
    ]);
    expect(screen.getAllByText(/Suggest setting/)).toHaveLength(2);
  });
});
