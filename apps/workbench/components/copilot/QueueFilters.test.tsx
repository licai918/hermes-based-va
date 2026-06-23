import { fireEvent, render, screen } from "@testing-library/react";
import { QueueFilters, type QueueFilter } from "./QueueFilters";

const baseValue: QueueFilter = {
  statuses: ["open", "in_progress"],
  assignee: "mine_or_unassigned",
};

function renderFilters(
  props: Partial<Parameters<typeof QueueFilters>[0]> = {},
) {
  const onChange = vi.fn();
  render(
    <QueueFilters
      value={baseValue}
      onChange={onChange}
      canViewAllTeam={false}
      {...props}
    />,
  );
  return { onChange };
}

describe("QueueFilters", () => {
  it("removes a status when its checkbox is unchecked", () => {
    const { onChange } = renderFilters();
    fireEvent.click(screen.getByLabelText("In progress"));
    expect(onChange).toHaveBeenCalledWith({
      statuses: ["open"],
      assignee: "mine_or_unassigned",
    });
  });

  it("adds a status when an unchecked box is checked", () => {
    const { onChange } = renderFilters({
      value: { statuses: ["in_progress"], assignee: "mine_or_unassigned" },
    });
    fireEvent.click(screen.getByLabelText("Open"));
    expect(onChange).toHaveBeenCalledWith({
      statuses: ["in_progress", "open"],
      assignee: "mine_or_unassigned",
    });
  });

  it("hides the resolved widening + All team option from reps", () => {
    renderFilters({ canViewAllTeam: false });
    expect(screen.queryByLabelText("Resolved")).toBeNull();
    expect(screen.queryByRole("option", { name: "All team" })).toBeNull();
  });

  it("offers resolved + All team to supervisors/admins", () => {
    renderFilters({ canViewAllTeam: true });
    expect(screen.getByLabelText("Resolved")).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "All team" })).toBeInTheDocument();
  });

  it("changes the assignee mode via the select", () => {
    const { onChange } = renderFilters({ canViewAllTeam: true });
    fireEvent.change(screen.getByLabelText("Assignee"), {
      target: { value: "all" },
    });
    expect(onChange).toHaveBeenCalledWith({
      statuses: ["open", "in_progress"],
      assignee: "all",
    });
  });
});
