from __future__ import annotations

import re

from app.schemas import AuditResult, RiskBreakdown


_MONEY = re.compile(
    r"\$\s*(?P<number>\d{1,3}(?:,\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?)\s*"
    r"(?P<scale>billion|million|thousand|[bmk])?\b",
    re.IGNORECASE,
)
_SCALES = {
    "b": 1_000_000_000, "billion": 1_000_000_000,
    "m": 1_000_000, "million": 1_000_000,
    "k": 1_000, "thousand": 1_000,
}


def monetary_values(text: str) -> list[float]:
    values: list[float] = []
    for match in _MONEY.finditer(text or ""):
        number = float(match.group("number").replace(",", ""))
        values.append(number * _SCALES.get((match.group("scale") or "").lower(), 1))
    return values


def calculate_risk(
    audit: AuditResult,
    draft: str,
    research_text: str,
    used_researcher: bool,
    materiality_threshold: float = 10_000_000,
    forced: bool = False,
) -> RiskBreakdown:
    flags = 40 if audit.risk_flags else 0
    citations = 25 if audit.citation_issues else 0
    materiality = 20 if any(
        value > materiality_threshold for value in monetary_values(f"{draft}\n{research_text}")
    ) else 0
    live_research = 15 if used_researcher else 0
    return RiskBreakdown(
        flags=flags,
        citations=citations,
        materiality=materiality,
        live_research=live_research,
        total=min(100, flags + citations + materiality + live_research),
        forced=forced,
    )
