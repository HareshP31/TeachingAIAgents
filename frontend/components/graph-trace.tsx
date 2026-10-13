import {Ban, Check, Pause, RotateCcw} from "lucide-react";
import type {LogRow} from "@/lib/types";

const pipeline = ["ScopeGate", "Route", "Researcher", "Analyst", "Auditor", "HumanReview", "Notify"];
// An off-topic question leaves the gate for Decline and never reaches the rest of the pipeline.
const declinedPath = ["ScopeGate", "Decline"];

export function GraphTrace({log}: {log: LogRow[]}) {
  const nodes = log.some(item => item.node === "Decline") ? declinedPath : pipeline;
  const reviewEvents = log.filter(item => item.node === "HumanReview");
  const waiting = reviewEvents.at(-1)?.status === "awaiting";
  const counts = Object.fromEntries(nodes.map(node => [node,
    node === "HumanReview"
      ? reviewEvents.filter(item => item.status === "completed").length + (waiting ? 1 : 0)
      : log.filter(item => item.node === node).length,
  ]));
  return <div className="graph" aria-label="Agent execution graph">
    {nodes.map((node, index) => {
      const count = counts[node] ?? 0;
      const lit = count > 0;
      return <div className="graph-step" key={node}>
        <div className={`graph-node ${lit ? "complete" : ""} ${node === "HumanReview" && waiting ? "waiting" : ""} ${node === "Decline" ? "declined" : ""}`}>
          <span className="node-icon">{node === "Decline" ? <Ban size={15}/> : node === "HumanReview" && waiting ? <Pause size={15}/> : lit ? <Check size={15}/> : <span/>}</span>
          <span>{node}</span>
          {count > 1 && <span className="counter"><RotateCcw size={11}/>{count}</span>}
        </div>
        {index < nodes.length - 1 && <div className={`connector ${lit && counts[nodes[index + 1]] ? "lit" : ""}`}/>}
      </div>;
    })}
  </div>;
}
