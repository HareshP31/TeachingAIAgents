"use client";

import {Cell, Pie, PieChart, ResponsiveContainer} from "recharts";
import type {RunDetail} from "@/lib/types";

export function RiskCard({run}: {run?: RunDetail}) {
  const score = run?.risk_score ?? 0;
  const chart = [{value: score}, {value: 100 - score}];
  return <section className="panel risk-panel">
    <div className="panel-heading"><span>Risk assessment</span><span className="eyebrow">DETERMINISTIC</span></div>
    <div className="risk-main">
      <div className="risk-chart">
        <ResponsiveContainer width="100%" height="100%">
          <PieChart><Pie data={chart} dataKey="value" innerRadius={44} outerRadius={55} startAngle={90} endAngle={-270} stroke="none">
            <Cell fill={score >= 50 ? "#f59e66" : "#69d5aa"}/><Cell fill="#223047"/>
          </Pie></PieChart>
        </ResponsiveContainer>
        <strong>{score}</strong><small>/100</small>
      </div>
      <div className="risk-state"><span className={`state-dot ${score >= 50 ? "warn" : "safe"}`}/>
        {run ? (run.review_status === "approved" ? "Human approved" : score >= 50 ? "Human review" : "Auto-approved") : "No run selected"}
      </div>
    </div>
    <div className="risk-breakdown">
      {Object.entries(run?.risk_breakdown ?? {}).filter(([key,value]) => typeof value === "number" && key !== "total").map(([key,value]) =>
        <div key={key}><span>{key.replaceAll("_", " ")}</span><b>+{String(value)}</b></div>)}
    </div>
    <div className="tags">{run?.risk_flags?.map(flag => <span key={flag}>{flag.replaceAll("_", " ")}</span>)}</div>
  </section>;
}
