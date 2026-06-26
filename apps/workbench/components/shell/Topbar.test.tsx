import { render, screen } from "@testing-library/react";
import { WORKBENCH_ROLES } from "@toee/shared";
import { Topbar } from "./Topbar";

describe("Topbar", () => {
  it("shows a rep only the Copilot nav link", () => {
    render(
      <Topbar username="rep1" role={WORKBENCH_ROLES.rep} pathname="/copilot" />,
    );
    expect(screen.getByRole("link", { name: "Copilot" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Knowledge" })).toBeNull();
    expect(screen.queryByRole("link", { name: "Accounts" })).toBeNull();
  });

  it("shows a supervisor the governance links and marks the active route", () => {
    render(
      <Topbar
        username="sup"
        role={WORKBENCH_ROLES.supervisor}
        pathname="/admin/knowledge"
      />,
    );
    expect(screen.getByRole("link", { name: "Knowledge" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(screen.getByRole("link", { name: "Eval" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Accounts" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Copilot" })).not.toHaveAttribute(
      "aria-current",
    );
  });
});
