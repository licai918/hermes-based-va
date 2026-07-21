import { render, screen } from "@testing-library/react";
import { QualityGatesPanel } from "./QualityGatesPanel";

// Static panel (S12, FR-7/FR-7b/FR-29) -- no fetching, so just a render/content
// check: every gate row's command + result is visible, and PASS/FAIL chips
// reflect the recorded numbers (recall@3 is the one recorded FAIL).
describe("QualityGatesPanel", () => {
  it("renders every gate's command and last-recorded result", () => {
    render(<QualityGatesPanel />);

    expect(screen.getByText("python -m hermes_runtime.knowledge.gates recall")).toBeInTheDocument();
    expect(screen.getAllByText("python -m hermes_runtime.knowledge.gates latency")).toHaveLength(2);
    expect(screen.getByText("python -m eval_runner.judge_measure --live")).toBeInTheDocument();
    expect(screen.getByText(/22\/30 = 73%/)).toBeInTheDocument();
    expect(screen.getByText(/p95 48\.4ms/)).toBeInTheDocument();
  });

  it("shows FAIL for the below-bar recall gate and PASS for the others", () => {
    render(<QualityGatesPanel />);

    const chips = screen.getAllByText(/^(PASS|FAIL)$/);
    expect(chips.map((c) => c.textContent)).toEqual(["FAIL", "PASS", "PASS", "PASS"]);
  });
});
