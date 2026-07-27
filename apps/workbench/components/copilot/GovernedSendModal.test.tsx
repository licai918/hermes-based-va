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
  const { body, ...rest } = props;
  render(
    <ErrorBannerProvider>
      <GlobalErrorBanner />
      <GovernedSendModal
        caseId="c1"
        body={body ?? "Your tires are ready for pickup."}
        accountId="acct-1"
        onSent={onSent}
        onClose={onClose}
        send={send}
        {...rest}
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

// 0.0.4 S09: implicit sent_as_is/sent_edited capture on a successful governed
// send only, fire-and-forget so it can never block the modal or surface an
// error to the rep. `body` is the (possibly edited) text actually sent;
// `originalBody` is the draft as generated.
describe("GovernedSendModal implicit outcome capture (S09)", () => {
  const GENERATED = "Your tires are ready for pickup.";

  it("records sent_as_is when the draft is sent untouched, with no ratio", async () => {
    const recordOutcome = vi.fn().mockResolvedValue({ recorded: true });
    const { onSent } = renderModal({
      body: GENERATED,
      originalBody: GENERATED,
      draftCorrelationId: "corr-1",
      draftKind: "sms",
      recordOutcome,
    });

    fireEvent.click(screen.getByRole("button", { name: /confirm/i }));
    await waitFor(() => expect(onSent).toHaveBeenCalledTimes(1));

    expect(recordOutcome).toHaveBeenCalledWith({
      caseId: "c1",
      draftCorrelationId: "corr-1",
      draftKind: "sms",
      draftText: GENERATED,
      outcome: "sent_as_is",
    });
  });

  it("records sent_edited with a plausible ratio when the draft was edited before sending", async () => {
    const recordOutcome = vi.fn().mockResolvedValue({ recorded: true });
    const edited = "Your tires are ready for pickup today!";
    const { onSent } = renderModal({
      body: edited,
      originalBody: GENERATED,
      draftCorrelationId: "corr-2",
      draftKind: "sms",
      recordOutcome,
    });

    fireEvent.click(screen.getByRole("button", { name: /confirm/i }));
    await waitFor(() => expect(onSent).toHaveBeenCalledTimes(1));

    expect(recordOutcome).toHaveBeenCalledTimes(1);
    const call = recordOutcome.mock.calls[0]?.[0];
    expect(call).toMatchObject({
      caseId: "c1",
      draftCorrelationId: "corr-2",
      draftKind: "sms",
      draftText: GENERATED,
      outcome: "sent_edited",
    });
    expect(typeof call.editDistanceRatio).toBe("number");
    expect(call.editDistanceRatio).toBeGreaterThan(0);
    expect(call.editDistanceRatio).toBeLessThanOrEqual(1);
  });

  it("treats a whitespace-only difference as sent_as_is (trim boundary)", async () => {
    const recordOutcome = vi.fn().mockResolvedValue({ recorded: true });
    const { onSent } = renderModal({
      body: `  ${GENERATED}\n`,
      originalBody: GENERATED,
      draftCorrelationId: "corr-3",
      draftKind: "sms",
      recordOutcome,
    });

    fireEvent.click(screen.getByRole("button", { name: /confirm/i }));
    await waitFor(() => expect(onSent).toHaveBeenCalledTimes(1));

    expect(recordOutcome).toHaveBeenCalledWith(
      expect.objectContaining({ outcome: "sent_as_is" }),
    );
  });

  it("a failing outcome call does not fail the send, surface an error, or block closing", async () => {
    const recordOutcome = vi.fn().mockRejectedValue(new Error("feedback route down"));
    const { onSent, onClose } = renderModal({
      body: GENERATED,
      originalBody: GENERATED,
      draftCorrelationId: "corr-4",
      draftKind: "sms",
      recordOutcome,
    });

    fireEvent.click(screen.getByRole("button", { name: /confirm/i }));

    await waitFor(() => expect(onSent).toHaveBeenCalledTimes(1));
    expect(onClose).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(recordOutcome).toHaveBeenCalledTimes(1));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("a SYNCHRONOUSLY throwing outcome call still does not fail the send", async () => {
    // The .catch() on the returned promise only covers an ASYNC rejection. A
    // recordOutcome that throws synchronously (a non-async injected impl, or a
    // throw from the ratio computation in its argument list) escapes it, lands
    // in confirm()'s try, and is caught by the SEND's error handler -- so the
    // customer's message has already gone out, but the rep is told the send
    // failed and the modal never closes. The rep then retries -> duplicate SMS.
    const recordOutcome = vi.fn().mockImplementation(() => {
      throw new Error("synchronous boom");
    });
    const { onSent, onClose } = renderModal({
      body: GENERATED,
      originalBody: GENERATED,
      draftCorrelationId: "corr-sync",
      draftKind: "sms",
      recordOutcome,
    });

    fireEvent.click(screen.getByRole("button", { name: /confirm/i }));

    await waitFor(() => expect(onSent).toHaveBeenCalledTimes(1));
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("records no outcome when the send itself fails", async () => {
    const recordOutcome = vi.fn().mockResolvedValue({ recorded: true });
    const send = vi.fn().mockRejectedValue(new ApiError(502, "SMS provider unavailable"));
    renderModal({
      body: GENERATED,
      originalBody: GENERATED,
      draftCorrelationId: "corr-5",
      draftKind: "sms",
      recordOutcome,
      send,
    });

    fireEvent.click(screen.getByRole("button", { name: /confirm/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent("SMS provider unavailable");

    expect(recordOutcome).not.toHaveBeenCalled();
  });
});
