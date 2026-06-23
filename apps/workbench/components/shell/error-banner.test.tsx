import { fireEvent, render, screen } from "@testing-library/react";
import {
  ErrorBannerProvider,
  GlobalErrorBanner,
  useErrorBanner,
} from "./error-banner";

function Trigger() {
  const { showError } = useErrorBanner();
  return (
    <button type="button" onClick={() => showError("Tool failed", "ERR_TOOL")}>
      raise
    </button>
  );
}

describe("GlobalErrorBanner", () => {
  it("renders nothing until an error is raised", () => {
    render(
      <ErrorBannerProvider>
        <GlobalErrorBanner />
        <Trigger />
      </ErrorBannerProvider>,
    );
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("shows the message + reference, then dismisses", () => {
    render(
      <ErrorBannerProvider>
        <GlobalErrorBanner />
        <Trigger />
      </ErrorBannerProvider>,
    );
    fireEvent.click(screen.getByText("raise"));
    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("Tool failed");
    expect(alert).toHaveTextContent("ERR_TOOL");

    fireEvent.click(screen.getByRole("button", { name: /dismiss/i }));
    expect(screen.queryByRole("alert")).toBeNull();
  });
});
