import { render, screen } from "@testing-library/react";
import { IdleTimeoutModal, msUntilIdle } from "./IdleTimeoutModal";

describe("msUntilIdle", () => {
  it("returns positive ms while active and non-positive once elapsed", () => {
    expect(msUntilIdle(1000, 500, 1200)).toBe(300);
    expect(msUntilIdle(1000, 500, 2000)).toBeLessThanOrEqual(0);
  });
});

describe("IdleTimeoutModal", () => {
  it("does not render while the session is still active", () => {
    render(<IdleTimeoutModal lastActivityAt={Date.now()} idleMs={60_000} />);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("renders the expiry dialog once the idle window has elapsed", () => {
    render(
      <IdleTimeoutModal lastActivityAt={Date.now() - 120_000} idleMs={60_000} />,
    );
    const dialog = screen.getByRole("dialog");
    expect(dialog).toBeInTheDocument();
    expect(dialog).toHaveTextContent(/session expired/i);
  });
});
