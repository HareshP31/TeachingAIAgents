from app.schemas import AuditResult, CitationIssue, RiskFlag
from app.services.risk import calculate_risk, monetary_values


def test_parses_scaled_and_comma_currency() -> None:
    assert monetary_values("$382.7M and $10,000") == [382_700_000, 10_000]


def test_zero_risk_for_guidebook_only_valid_answer() -> None:
    result = calculate_risk(AuditResult(is_valid=True), "No amount", "", False)
    assert result.total == 0


def test_documented_cloud_one_score() -> None:
    result = calculate_risk(
        AuditResult(is_valid=True, risk_flags=[RiskFlag.VENDOR_LOCK_IN]),
        "The contract is $382.7M", "sourced research", True,
    )
    assert result.model_dump() == {
        "flags": 40, "citations": 0, "materiality": 20,
        "live_research": 15, "total": 75, "forced": False,
    }


def test_score_caps_at_100() -> None:
    result = calculate_risk(
        AuditResult(
            is_valid=False, risk_flags=[RiskFlag.VENDOR_LOCK_IN],
            citation_issues=[CitationIssue(citation="x", reason="bad")],
        ), "$2 billion", "", True,
    )
    assert result.total == 100


def test_materiality_is_strictly_above_threshold() -> None:
    assert calculate_risk(AuditResult(is_valid=True), "$10M", "", False).materiality == 0
