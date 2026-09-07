"""Auditor node: checks the Analyst's draft against source chunks for hallucinations,
stale citations, and named guidebook risks. Genuinely separate node/call from the
Analyst, with its own system prompt (same running LM Studio model instance).

Must return structured output {is_valid, risk_score, issues} via JSON-schema /
grammar-constrained decoding so the next graph edge can branch reliably.
See docs/project-architecture-plan.md sections 3-4.
"""

# TODO: call LM Studio with the Auditor system prompt + constrained decoding schema.
