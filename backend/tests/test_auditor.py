from app.agents.auditor import enforce_audit_consistency
from app.schemas import AuditResult, CitationIssue


def test_citation_issues_force_invalid_audit() -> None:
    result = enforce_audit_consistency(AuditResult(
        is_valid=True,
        citation_issues=[CitationIssue(citation="claim", reason="unsupported")],
    ))
    assert result.is_valid is False
