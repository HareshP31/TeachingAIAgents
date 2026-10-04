from __future__ import annotations

import asyncio
import hashlib

import httpx
import pytest

import app as nanobot_app

ALLOWED = ["sam.gov", "usaspending.gov"]
URL = "https://sam.gov/opp/123"
QUERY = "cloud contract vendor lock-in"
ARTICLE = (
    "<html><head><title>Opportunity</title></head><body><article>"
    + "<p>This solicitation covers a cloud contract with significant vendor lock-in risk. "
    "The government expects portability and exit planning to be addressed in every proposal.</p>" * 5
    + "</article></body></html>"
)
TEXT = {"content-type": "text/plain"}


def finding(url: str = URL) -> dict:
    return {"title": "Opp", "url": url, "excerpt": "original snippet", "snippet_only": True}


@pytest.fixture(autouse=True)
def public_hosts(monkeypatch):
    monkeypatch.setattr(nanobot_app, "host_is_public", lambda hostname: True)


async def fetch(item: dict | None = None, allowed: list[str] = ALLOWED) -> dict:
    return await nanobot_app.fetch_finding(item or finding(), QUERY, allowed)


def assert_snippet_fallback(result: dict, status: int | None) -> None:
    assert result["snippet_only"] is True
    assert result["http_status"] == status
    assert result["excerpt"] == "original snippet"
    assert "content_sha256" not in result


async def test_html_page_is_fetched_and_summarised(respx_mock) -> None:
    respx_mock.get(URL).respond(200, text=ARTICLE, headers={"content-type": "text/html; charset=utf-8"})
    result = await fetch()
    assert result["snippet_only"] is False
    assert result["http_status"] == 200
    assert "vendor lock-in" in result["excerpt"]
    assert "<p>" not in result["excerpt"]
    assert result["content_sha256"] == hashlib.sha256(ARTICLE.encode()).hexdigest()
    assert result["fetched_at"]


async def test_plain_text_is_accepted(respx_mock) -> None:
    respx_mock.get(URL).respond(200, text="The cloud contract has vendor lock-in.", headers=TEXT)
    result = await fetch()
    assert result["snippet_only"] is False
    assert result["excerpt"] == "The cloud contract has vendor lock-in."


async def test_sends_identifying_user_agent(respx_mock) -> None:
    route = respx_mock.get(URL).respond(200, text="cloud contract", headers=TEXT)
    await fetch()
    assert route.calls.last.request.headers["user-agent"].startswith("TeachingAIAgents/")


async def test_redirect_within_allowlist_is_followed_and_url_updated(respx_mock) -> None:
    final = "https://www.usaspending.gov/award/9"
    respx_mock.get(URL).respond(302, headers={"location": final})
    respx_mock.get(final).respond(200, text="cloud contract vendor lock-in", headers=TEXT)
    result = await fetch()
    assert result["url"] == final
    assert result["snippet_only"] is False


async def test_relative_redirect_is_resolved(respx_mock) -> None:
    respx_mock.get(URL).respond(301, headers={"location": "/opp/456"})
    respx_mock.get("https://sam.gov/opp/456").respond(200, text="cloud contract", headers=TEXT)
    result = await fetch()
    assert result["url"] == "https://sam.gov/opp/456"


async def test_redirect_off_allowlist_is_blocked_without_requesting_it(respx_mock) -> None:
    respx_mock.get(URL).respond(302, headers={"location": "https://evil.com/steal"})
    evil = respx_mock.get("https://evil.com/steal").respond(200, text="x", headers=TEXT)
    result = await fetch()
    assert_snippet_fallback(result, 302)
    assert not evil.called


async def test_redirect_to_non_http_scheme_is_blocked(respx_mock) -> None:
    respx_mock.get(URL).respond(302, headers={"location": "file:///etc/passwd"})
    assert_snippet_fallback(await fetch(), 302)


async def test_redirect_loop_stops_after_four_hops(respx_mock) -> None:
    route = respx_mock.get(URL).respond(302, headers={"location": URL})
    result = await fetch()
    assert_snippet_fallback(result, 302)
    assert route.call_count == 4


async def test_initial_url_off_allowlist_is_never_requested(respx_mock) -> None:
    route = respx_mock.get("https://evil.com/page").respond(200, text="x", headers=TEXT)
    result = await fetch(finding("https://evil.com/page"))
    assert_snippet_fallback(result, None)
    assert not route.called


async def test_non_public_host_is_never_requested(respx_mock, monkeypatch) -> None:
    monkeypatch.setattr(nanobot_app, "host_is_public", lambda hostname: False)
    route = respx_mock.get(URL).respond(200, text="x", headers=TEXT)
    assert_snippet_fallback(await fetch(), None)
    assert not route.called


async def test_redirect_target_resolving_privately_is_blocked(respx_mock, monkeypatch) -> None:
    monkeypatch.setattr(nanobot_app, "host_is_public", lambda hostname: hostname == "sam.gov")
    respx_mock.get(URL).respond(302, headers={"location": "https://www.usaspending.gov/internal"})
    internal = respx_mock.get("https://www.usaspending.gov/internal").respond(200, text="x", headers=TEXT)
    assert_snippet_fallback(await fetch(), 302)
    assert not internal.called


@pytest.mark.parametrize("content_type", ["application/pdf", "application/json", "image/png", ""])
async def test_unsupported_content_types_fall_back(respx_mock, content_type: str) -> None:
    respx_mock.get(URL).respond(200, content=b"data", headers={"content-type": content_type})
    assert_snippet_fallback(await fetch(), 200)


@pytest.mark.parametrize("status", [403, 404, 500])
async def test_error_statuses_fall_back_and_keep_the_status(respx_mock, status: int) -> None:
    respx_mock.get(URL).respond(status, text="nope", headers={"content-type": "text/html"})
    assert_snippet_fallback(await fetch(), status)


async def test_body_over_two_megabytes_falls_back(respx_mock) -> None:
    respx_mock.get(URL).respond(200, content=b"a" * (2 * 1024 * 1024 + 1), headers=TEXT)
    assert_snippet_fallback(await fetch(), 200)


async def test_body_at_the_limit_is_accepted(respx_mock) -> None:
    respx_mock.get(URL).respond(200, content=b"a" * (2 * 1024 * 1024), headers=TEXT)
    assert (await fetch())["snippet_only"] is False


async def test_empty_body_falls_back(respx_mock) -> None:
    respx_mock.get(URL).respond(200, content=b"   \n ", headers=TEXT)
    assert_snippet_fallback(await fetch(), 200)


async def test_network_error_falls_back_without_raising(respx_mock) -> None:
    respx_mock.get(URL).mock(side_effect=httpx.ConnectError("refused"))
    assert_snippet_fallback(await fetch(), None)


async def test_timeout_falls_back_without_raising(respx_mock) -> None:
    respx_mock.get(URL).mock(side_effect=httpx.ReadTimeout("slow"))
    assert_snippet_fallback(await fetch(), None)


async def test_enrich_preserves_order_and_caps_concurrency(monkeypatch) -> None:
    active = peak = 0

    async def slow_fetch(item, query, allowed):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.01)
        active -= 1
        return {**item, "fetched": True}

    monkeypatch.setattr(nanobot_app, "fetch_finding", slow_fetch)
    items = [{"url": f"https://sam.gov/{i}"} for i in range(8)]
    results = await nanobot_app.enrich_findings(items, QUERY, ALLOWED)
    assert [r["url"] for r in results] == [i["url"] for i in items]
    assert all(r["fetched"] for r in results)
    assert peak == 3


def test_excerpt_starts_before_the_first_matching_term() -> None:
    text = "alpha " * 200 + "needle-term sits here " + "omega " * 400
    excerpt = nanobot_app.relevant_excerpt(text, "find the needle-term")
    assert "needle-term" in excerpt
    assert len(excerpt) <= 1800


def test_excerpt_with_no_matching_term_starts_at_the_beginning() -> None:
    assert nanobot_app.relevant_excerpt("start of page " + "x" * 3000, "zzzzzz").startswith("start of page")


def test_excerpt_ignores_short_query_words() -> None:
    text = "the cat sat " + "filler " * 300 + "contract details"
    assert nanobot_app.relevant_excerpt(text, "a of the").startswith("the cat sat")


def test_excerpt_collapses_whitespace_and_respects_limit() -> None:
    excerpt = nanobot_app.relevant_excerpt("a  \n\n b\t\tc " * 1000, "none", limit=50)
    assert "  " not in excerpt and "\n" not in excerpt
    assert len(excerpt) == 50
