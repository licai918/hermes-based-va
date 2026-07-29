import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { EXTERNAL_REVIEW_REASON_TAGS, WORKBENCH_ROLES } from "@toee/shared";
import { PREFERENCE_SHAPED_TAGS, ReviewBar, memoryCorrectionHref } from "./ReviewBar";

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

  // --- US-7/FR-5: a supervisor reopening a record sees their prior verdict ---

  it("renders the unreviewed state when no initial review is supplied", () => {
    renderBar();
    expect(screen.getByText("Pass")).toBeInTheDocument();
    expect(screen.getByText("Fail")).toBeInTheDocument();
    expect(screen.queryByText(/Reviewed:/)).toBeNull();
  });

  it("renders the prior verdict, tags, and comment on load when supplied", () => {
    renderBar({
      initialReview: {
        verdict: "fail",
        reasonTags: ["factual_error", "policy_violation"],
        comment: "gave the wrong ETA",
      },
    });

    const region = screen.getByRole("region", { name: "Review" });
    expect(region).toHaveTextContent(/Reviewed:\s*Fail/);
    expect(region).toHaveTextContent("Factual error");
    expect(region).toHaveTextContent("Policy violation");
    expect(region).toHaveTextContent("gave the wrong ETA");
    expect(screen.getByText("Edit review")).toBeInTheDocument();
    expect(screen.queryByText("Pass")).toBeNull();
  });

  it("the edit affordance on a prior review still submits and appends a new row", async () => {
    const submit = vi.fn().mockResolvedValue({ review: { id: "irev_2" } });
    renderBar({
      submit,
      initialReview: { verdict: "pass", reasonTags: [] },
    });

    fireEvent.click(screen.getByText("Edit review"));
    fireEvent.click(screen.getByText("Fail"));
    fireEvent.click(screen.getByText("Tool misuse"));
    fireEvent.click(screen.getByText("Submit fail"));

    await waitFor(() =>
      expect(submit).toHaveBeenCalledWith({
        subjectKind: "auto_handled_record",
        subjectId: "rec-1",
        verdict: "fail",
        reasonTags: ["tool_misuse"],
        comment: undefined,
      }),
    );
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

// --- 0.0.5 S17 (FR-25/US12): the prefilled L4 correction --------------------

describe("memoryCorrectionHref", () => {
  const failing = {
    subjectKind: "sales_outreach_case" as const,
    subjectId: "case_ar_urgent",
    reasonTags: ["tone_inappropriate" as const],
    comment: "customer asked us to stop being so chatty",
  };

  it("carries the slot, the case, and the supervisor's comment as the value", () => {
    const params = new URL(
      memoryCorrectionHref(failing) as string,
      "http://localhost",
    ).searchParams;
    expect(params.get("slot")).toBe("communication_style_note");
    expect(params.get("case")).toBe("case_ar_urgent");
    expect(params.get("value")).toBe("customer asked us to stop being so chatty");
    expect(params.get("tag")).toBe("tone_inappropriate");
    expect(params.get("from")).toBe("sales_outreach_case:case_ar_urgent");
  });

  // The exclusion cases the fixture rule asks for. The list is EXTERNAL_REVIEW_
  // REASON_TAGS minus the one literal tag this feature claims — deliberately
  // NOT `filter(t => !PREFERENCE_SHAPED_TAGS[t])`, which is what it said first
  // and which could not fail: deriving the cases from the map under test means
  // widening the map removes the case that would have caught the widening.
  // Proven by baiting it (adding `tool_misuse` left it green, 6 cases silently
  // becoming 5). Filtering by literal keeps the enum-derived coverage — a tag
  // added later lands here automatically and must not be preference-shaped —
  // while making the map's growth visible.
  it.each(EXTERNAL_REVIEW_REASON_TAGS.filter((t) => t !== "tone_inappropriate"))(
    "offers nothing for %s, which is not preference-shaped",
    (tag) => {
      expect(memoryCorrectionHref({ ...failing, reasonTags: [tag] })).toBeNull();
    },
  );

  it("claims exactly one preference-shaped tag, and no more", () => {
    // The intent, stated rather than inferred: widening what counts as
    // "preference-shaped" is a product decision (which slot? on what evidence?),
    // so it must be a deliberate edit here and not a quiet dictionary entry.
    expect(PREFERENCE_SHAPED_TAGS).toEqual({
      tone_inappropriate: "communication_style_note",
    });
  });

  it("offers the link when a preference-shaped tag rides alongside others", () => {
    expect(
      memoryCorrectionHref({
        ...failing,
        reasonTags: ["policy_violation", "tone_inappropriate"],
      }),
    ).not.toBeNull();
  });

  it("omits the case for an auto-handled record, which has none", () => {
    // Half a derivation is still useful and must not be silently dropped: the
    // slot and value still travel, and the console asks for the case id.
    const href = memoryCorrectionHref({
      ...failing,
      subjectKind: "auto_handled_record",
      subjectId: "rec-1",
    }) as string;
    const params = new URL(href, "http://localhost").searchParams;
    expect(params.get("case")).toBeNull();
    expect(params.get("slot")).toBe("communication_style_note");
    expect(params.get("from")).toBe("auto_handled_record:rec-1");
  });

  it("omits the value when the supervisor left no comment", () => {
    // No guessed value: the console opens with the slot chosen and the value
    // blank and editable, never a fabricated preference.
    const params = new URL(
      memoryCorrectionHref({ ...failing, comment: "   " }) as string,
      "http://localhost",
    ).searchParams;
    expect(params.get("value")).toBeNull();
  });

  it("truncates a comment to what an L4 slot value can actually hold", () => {
    const href = memoryCorrectionHref({ ...failing, comment: "x".repeat(400) }) as string;
    expect(new URL(href, "http://localhost").searchParams.get("value")).toHaveLength(200);
  });
});

describe("ReviewBar correction link", () => {
  it("appears after a fail with a preference-shaped tag", async () => {
    renderBar({ subjectKind: "sales_outreach_case", subjectId: "case_ar_urgent" });
    fireEvent.click(screen.getByText("Fail"));
    fireEvent.click(screen.getByText("Tone inappropriate"));
    fireEvent.change(screen.getByLabelText("Comment"), {
      target: { value: "too chatty" },
    });
    fireEvent.click(screen.getByText("Submit fail"));

    const link = await screen.findByRole("link", { name: /correct this customer/i });
    expect(link).toHaveAttribute(
      "href",
      expect.stringContaining("slot=communication_style_note"),
    );
    expect(link).toHaveAttribute("href", expect.stringContaining("case=case_ar_urgent"));
  });

  it("does not appear on a PASS, whatever the tags say", () => {
    renderBar({ initialReview: { verdict: "pass", reasonTags: ["tone_inappropriate"] } });
    expect(screen.queryByRole("link", { name: /correct this customer/i })).toBeNull();
  });

  it("does not appear on a fail whose cause is not preference-shaped", () => {
    renderBar({ initialReview: { verdict: "fail", reasonTags: ["tool_misuse"] } });
    expect(screen.queryByRole("link", { name: /correct this customer/i })).toBeNull();
  });
});
