import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { ApiError } from "@/lib/api/http";
import {
  ErrorBannerProvider,
  GlobalErrorBanner,
} from "@/components/shell/error-banner";
import { GovernedSendModal } from "./GovernedSendModal";

function renderModal(props: Partial<Parameters<typeof GovernedSendModal>[0]> = {}) {
  const onSent = vi.fn();
  const onClose = vi.fn();
  const send = props.send ?? vi.fn().mockResolvedValue({ message: { messageId: "m1" } });
  render(
    <ErrorBannerProvider>
      <GlobalErrorBanner />
      <GovernedSendModal
        caseId="c1"
        body="Your tires are ready for pickup."
        accountId="acct-1"
        onSent={onSent}
        onClose={onClose}
        send={send}
      />
    </ErrorBannerProvider>,
  );
  return { onSent, onClose, send };
}

describe("GovernedSendModal", () => {
  it("shows a dialog previewing the outbound body and case", () => {
    renderModal();
    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveTextContent("Your tires are ready for pickup.");
    expect(dialog).toHaveTextContent("c1");
  });

  it("sends on confirm, then fires onSent and onClose", async () => {
    const { onSent, onClose, send } = renderModal();
    fireEvent.click(screen.getByRole("button", { name: /confirm/i }));
    await waitFor(() => expect(send).toHaveBeenCalledWith("c1", "Your tires are ready for pickup."));
    await waitFor(() => expect(onSent).toHaveBeenCalledTimes(1));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("surfaces the error and keeps the modal open when the send fails", async () => {
    const send = vi.fn().mockRejectedValue(new ApiError(502, "SMS provider unavailable"));
    const { onSent, onClose } = renderModal({ send });
    fireEvent.click(screen.getByRole("button", { name: /confirm/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent("SMS provider unavailable");
    expect(onSent).not.toHaveBeenCalled();
    expect(onClose).not.toHaveBeenCalled();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("cancels without sending", () => {
    const { onClose, send } = renderModal();
    fireEvent.click(screen.getByRole("button", { name: /cancel/i }));
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(send).not.toHaveBeenCalled();
  });
});
