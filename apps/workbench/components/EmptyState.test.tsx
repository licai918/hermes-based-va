import { render, screen } from "@testing-library/react";
import { EmptyState } from "./EmptyState";

describe("EmptyState", () => {
  it("renders the title", () => {
    render(<EmptyState title="No open cases" />);
    expect(screen.getByText("No open cases")).toBeInTheDocument();
  });

  it("renders an optional description when provided", () => {
    render(
      <EmptyState title="No cases" description="Your queue is clear." />,
    );
    expect(screen.getByText("Your queue is clear.")).toBeInTheDocument();
  });

  it("omits the description element when none is given", () => {
    const { container } = render(<EmptyState title="No cases" />);
    expect(container.querySelector("p")).toBeNull();
  });
});
