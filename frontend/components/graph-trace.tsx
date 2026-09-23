import {Check, Pause, RotateCcw} from "lucide-react";
import type {LogRow} from "@/lib/types";

const nodes = ["Route", "Researcher", "Analyst", "Auditor", "HumanReview", "Notify"];

export function GraphTrace({log}: {log: LogRow[]}) {
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
        <div className={`graph-node ${lit ? "complete" : ""} ${node === "HumanReview" && waiting ? "waiting" : ""}`}>
          <span className="node-icon">{node === "HumanReview" && waiting ? <Pause size={15}/> : lit ? <Check size={15}/> : <span/>}</span>
          <span>{node}</span>
          {count > 1 && <span className="counter"><RotateCcw size={11}/>{count}</span>}
        </div>
        {index < nodes.length - 1 && <div className={`connector ${lit && counts[nodes[index + 1]] ? "lit" : ""}`}/>}
      </div>;
    })}
  </div>;
}
