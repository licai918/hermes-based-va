import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { WORKBENCH_ROLES } from "@toee/shared";
import { ReviewBar } from "./ReviewBar";

// 0.0.4 S04: component states mirroring GovernedSendModal.test.tsx's injected-
// callback pattern -- `submit` is passed in so the test never touches global
// fetch. unreviewed / reviewed / fail-expanded / rep-hidden per the S04 brief.

function renderBar(props: Partial<Parameters<typeof ReviewBar>[0]> = {}) {
  const submit = props.submit ?? vi.fn().mockResolvedValue({ review: { id: "irev_1" } });
  render(
    <ReviewBar
      role={WORKBENCH_ROLES.supervisor}
      subjectKind="auto_handled_record"
      subjectId="rec-1"
      submit={submit}
      {...props}
    />,
  );
  return { submit };
}

describe("ReviewBar", () => {
  it("is hidden for a rep", () => {
    renderBar({ role: WORKBENCH_ROLES.rep });
    expect(screen.queryByRole("region", { name: /review/i })).toBeNull();
    expect(screen.queryByText("Pass")).toBeNull();
  });

  it("is hidden when no role is supplied", () => {
    renderBar({ role: undefined });
    expect(screen.queryByText("Pass")).toBeNull();
  });

  it("shows Pass/Fail controls (unreviewed) for a supervisor", () => {
    renderBar({ role: WORKBENCH_ROLES.supervisor });
    expect(screen.getByText("Pass")).toBeInTheDocument();
    expect(screen.getByText("Fail")).toBeInTheDocument();
  });

  it("shows the controls for an admin too", () => {
    renderBar({ role: WORKBENCH_ROLES.admin });
    expect(screen.getByText("Pass")).toBeInTheDocument();
  });

  it("submits a one-click pass with an empty tag list", async () => {
    const { submit } = renderBar();
    fireEvent.click(screen.getByText("Pass"));
    await waitFor(() =>
      expect(submit).toHaveBeenCalledWith({
        subjectKind: "auto_handled_record",
        subjectId: "rec-1",
        verdict: "pass",
        reasonTags: [],
        comment: undefined,
      }),
    );
  });

  it("expands the reason-tag chips + comment on Fail, and disables submit until a tag is picked", async () => {
    renderBar();
    fireEvent.click(screen.getByText("Fail"));
    expect(screen.getByText("Factual error")).toBeInTheDocument();
    expect(screen.getByLabelText("Comment")).toBeInTheDocument();
    expect(screen.getByText("Submit fail")).toBeDisabled();

    fireEvent.click(screen.getByText("Factual error"));
    expect(screen.getByText("Submit fail")).not.toBeDisabled();
  });

  it("submits a fail with the selected tags and comment", async () => {
    const { submit } = renderBar();
    fireEvent.click(screen.getByText("Fail"));
    fireEvent.click(screen.getByText("Factual error"));
    fireEvent.click(screen.getByText("Tone inappropriate"));
    fireEvent.change(screen.getByLabelText("Comment"), {
      target: { value: "gave the wrong ETA" },
    });
    fireEvent.click(screen.getByText("Submit fail"));

    await waitFor(() =>
      expect(submit).toHaveBeenCalledWith({
        subjectKind: "auto_handled_record",
        subjectId: "rec-1",
        verdict: "fail",
        reasonTags: ["factual_error", "tone_inappropriate"],
        comment: "gave the wrong ETA",
      }),
    );
  });

  it("after a successful submit, shows the reviewed state with an edit affordance", async () => {
    renderBar();
    fireEvent.click(screen.getByText("Fail"));
    fireEvent.click(screen.getByText("Factual error"));
    fireEvent.click(screen.getByText("Submit fail"));

    const region = await screen.findByRole("region", { name: "Review" });
    await waitFor(() => expect(region).toHaveTextContent(/Reviewed:\s*Fail/));
    expect(region).toHaveTextContent("Factual error");
    expect(screen.getByText("Edit review")).toBeInTheDocument();
    expect(screen.queryByText("Submit fail")).toBeNull();
  });

  it("edit affordance reopens the form and a re-submit appends a new row (calls submit again)", async () => {
    const submit = vi.fn().mockResolvedValue({ review: { id: "irev_1" } });
    renderBar({ submit });
    fireEvent.click(screen.getByText("Pass"));
    expect(await screen.findByText("Edit review")).toBeInTheDocument();

    fireEvent.click(screen.getByText("Edit review"));
    expect(screen.getByText("Pass")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Fail"));
    fireEvent.click(screen.getByText("Should have escalated"));
    fireEvent.click(screen.getByText("Submit fail"));

    await waitFor(() => expect(submit).toHaveBeenCalledTimes(2));
    expect(submit).toHaveBeenLastCalledWith({
      subjectKind: "auto_handled_record",
      subjectId: "rec-1",
      verdict: "fail",
      reasonTags: ["should_have_escalated"],
      comment: undefined,
    });
  });

  it("surfaces a submit failure without losing the form", async () => {
    const submit = vi.fn().mockRejectedValue(new Error("network down"));
    renderBar({ submit });
    fireEvent.click(screen.getByText("Pass"));
    expect(await screen.findByRole("alert")).toHaveTextContent("network down");
    // Still shows the Pass/Fail controls -- nothing was recorded as reviewed.
    expect(screen.getByText("Pass")).toBeInTheDocument();
  });
});
