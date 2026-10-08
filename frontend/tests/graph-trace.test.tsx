import {render, screen, within} from "@testing-library/react";
import {describe, expect, it} from "vitest";
import {GraphTrace} from "@/components/graph-trace";
import {makeLog} from "./fixtures";

const NODES = ["Route", "Researcher", "Analyst", "Auditor", "HumanReview", "Notify"];

function node(name: string): HTMLElement {
  return screen.getByText(name).closest(".graph-node") as HTMLElement;
}

function litConnectors(container: HTMLElement): number[] {
  return [...container.querySelectorAll(".connector")]
    .map((element, index) => (element.classList.contains("lit") ? index : -1))
    .filter(index => index >= 0);
}

describe("GraphTrace", () => {
  it("renders all six stages in order with nothing lit for an empty log", () => {
    const {container} = render(<GraphTrace log={[]}/>);
    expect([...container.querySelectorAll(".graph-node")].map(el => el.textContent)).toEqual(NODES);
    expect(container.querySelectorAll(".complete")).toHaveLength(0);
    expect(container.querySelectorAll(".connector")).toHaveLength(NODES.length - 1);
    expect(litConnectors(container)).toEqual([]);
    expect(screen.getByLabelText("Agent execution graph")).toBeInTheDocument();
  });

  it("lights the stages that have run", () => {
    render(<GraphTrace log={[makeLog("Route"), makeLog("Analyst"), makeLog("Auditor")]}/>);
    for (const name of ["Route", "Analyst", "Auditor"]) expect(node(name)).toHaveClass("complete");
    for (const name of ["Researcher", "HumanReview", "Notify"]) expect(node(name)).not.toHaveClass("complete");
  });

  it("only lights a connector when both ends have run", () => {
    // Route -> Analyst skips Researcher: Route/Researcher and Researcher/Analyst stay dark.
    const {container} = render(<GraphTrace log={[makeLog("Route"), makeLog("Analyst"), makeLog("Auditor")]}/>);
    expect(litConnectors(container)).toEqual([2]); // Analyst -> Auditor
  });

  it("lights the whole path for a full run", () => {
    const log = NODES.map(name => makeLog(name, name === "HumanReview" ? {status: "completed"} : {}));
    const {container} = render(<GraphTrace log={log}/>);
    expect(litConnectors(container)).toEqual([0, 1, 2, 3, 4]);
  });

  it("shows a revision counter once a stage has run more than once", () => {
    render(<GraphTrace log={[
      makeLog("Researcher"), makeLog("Researcher"), makeLog("Analyst"), makeLog("Analyst"),
      makeLog("Analyst"), makeLog("Auditor"),
    ]}/>);
    expect(within(node("Researcher")).getByText("2")).toBeInTheDocument();
    expect(within(node("Analyst")).getByText("3")).toBeInTheDocument();
    expect(node("Auditor").querySelector(".counter")).toBeNull();
  });

  it("marks HumanReview as waiting while the latest review event is awaiting", () => {
    render(<GraphTrace log={[makeLog("Auditor"), makeLog("HumanReview", {status: "awaiting"})]}/>);
    expect(node("HumanReview")).toHaveClass("waiting");
    expect(node("HumanReview")).toHaveClass("complete");
    expect(node("Notify")).not.toHaveClass("complete");
  });

  it("stops waiting once the review completes", () => {
    render(<GraphTrace log={[
      makeLog("HumanReview", {status: "awaiting"}), makeLog("HumanReview", {status: "completed"}),
      makeLog("Notify"),
    ]}/>);
    expect(node("HumanReview")).not.toHaveClass("waiting");
    expect(node("HumanReview")).toHaveClass("complete");
  });

  it("counts a rejected review that is awaiting again as a second pass", () => {
    render(<GraphTrace log={[
      makeLog("HumanReview", {status: "awaiting"}), makeLog("HumanReview", {status: "completed"}),
      makeLog("HumanReview", {status: "awaiting"}),
    ]}/>);
    expect(node("HumanReview")).toHaveClass("waiting");
    expect(within(node("HumanReview")).getByText("2")).toBeInTheDocument();
  });

  it("does not count the awaiting event of a finished review twice", () => {
    render(<GraphTrace log={[
      makeLog("HumanReview", {status: "awaiting"}), makeLog("HumanReview", {status: "completed"}),
    ]}/>);
    expect(node("HumanReview").querySelector(".counter")).toBeNull();
  });
});
