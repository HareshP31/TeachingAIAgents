import {render, screen} from "@testing-library/react";
import {describe, expect, it} from "vitest";
import {RiskCard} from "@/components/risk-card";
import {makeRunDetail} from "./fixtures";

describe("RiskCard", () => {
  it("shows an empty state when no run is selected", () => {
    const {container} = render(<RiskCard/>);
    expect(screen.getByText("No run selected")).toBeInTheDocument();
    expect(screen.getByText("0")).toBeInTheDocument();
    expect(container.querySelector(".state-dot")).toHaveClass("safe");
    expect(container.querySelector(".risk-breakdown")).toBeEmptyDOMElement();
    expect(container.querySelector(".tags")).toBeEmptyDOMElement();
  });

  it.each([
    [0, "Auto-approved", "safe"],
    [49, "Auto-approved", "safe"],
    [50, "Human review", "warn"],
    [80, "Human review", "warn"],
    [100, "Human review", "warn"],
  ])("score %i is labelled %s", (score, label, dot) => {
    const {container} = render(<RiskCard run={makeRunDetail({risk_score: score})}/>);
    expect(screen.getByText(label)).toBeInTheDocument();
    expect(screen.getByText(String(score))).toBeInTheDocument();
    expect(container.querySelector(".state-dot")).toHaveClass(dot);
  });

  it("says a human approved regardless of score once the review is approved", () => {
    render(<RiskCard run={makeRunDetail({risk_score: 80, review_status: "approved"})}/>);
    expect(screen.getByText("Human approved")).toBeInTheDocument();
  });

  it("keeps the review label while a review is pending or rejected", () => {
    const {rerender} = render(<RiskCard run={makeRunDetail({risk_score: 80, review_status: "pending"})}/>);
    expect(screen.getByText("Human review")).toBeInTheDocument();
    rerender(<RiskCard run={makeRunDetail({risk_score: 80, review_status: "rejected"})}/>);
    expect(screen.getByText("Human review")).toBeInTheDocument();
  });

  it("lists numeric breakdown components with spaces for underscores", () => {
    const {container} = render(<RiskCard run={makeRunDetail({
      risk_score: 75,
      risk_breakdown: {total: 75, vendor_lock_in: 30, materiality_over_threshold: 25, forced_escalation: 20},
    })}/>);
    const rows = [...container.querySelectorAll(".risk-breakdown > div")].map(row => row.textContent);
    expect(rows).toEqual([
      "vendor lock in+30", "materiality over threshold+25", "forced escalation+20",
    ]);
  });

  it("omits the total and non-numeric entries from the breakdown", () => {
    const {container} = render(<RiskCard run={makeRunDetail({
      risk_breakdown: {total: 40, forced: true, snippet_penalty: 40},
    })}/>);
    const rows = [...container.querySelectorAll(".risk-breakdown > div")].map(row => row.textContent);
    expect(rows).toEqual(["snippet penalty+40"]);
  });

  it("renders risk flags as tags", () => {
    render(<RiskCard run={makeRunDetail({risk_flags: ["vendor_lock_in", "hidden_consumption_costs"]})}/>);
    expect(screen.getByText("vendor lock in")).toBeInTheDocument();
    expect(screen.getByText("hidden consumption costs")).toBeInTheDocument();
  });

  it("tolerates a run payload without flags or breakdown", () => {
    const run = {...makeRunDetail(), risk_flags: undefined, risk_breakdown: undefined} as never;
    expect(() => render(<RiskCard run={run}/>)).not.toThrow();
  });
});
