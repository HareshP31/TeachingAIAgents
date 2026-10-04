from __future__ import annotations

import asyncio
import logging
import time

import pytest
from fastapi.testclient import TestClient

import app as nanobot_app

QUERY = "Who holds the Cloud One contract?"
BODY = {"run_id": "run-1", "query": QUERY}
DEFAULT_SITES = ["sam.gov", "usaspending.gov"]


class FakeProcess:
    def __init__(self, stdout: bytes = b"", stderr: bytes = b"", returncode: int = 0, hang: bool = False) -> None:
        self._stdout, self._stderr, self._hang = stdout, stderr, hang
        self.returncode: int | None = None if hang else returncode
        self.terminated = self.killed = False

    async def communicate(self):
        if self._hang:
            await asyncio.sleep(3600)
        return self._stdout, self._stderr

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = -15

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9

    async def wait(self) -> int:
        return self.returncode or 0


@pytest.fixture
def spawn(monkeypatch):
    """Replace the nanobot subprocess; the handle exposes the fake process and recorded argv."""
    class Handle:
        process = FakeProcess()
        argv: tuple = ()
        calls = 0

    async def create(*argv, **kwargs):
        Handle.argv, Handle.calls = argv, Handle.calls + 1
        return Handle.process

    monkeypatch.setattr(nanobot_app.asyncio, "create_subprocess_exec", create)
    return Handle


@pytest.fixture
def enrich(monkeypatch):
    """Skip real page fetching; tag every finding so tests can see enrichment ran."""
    async def fake_enrich(findings, query, allowed):
        return [{**item, "enriched": True, "snippet_only": False} for item in findings]

    monkeypatch.setattr(nanobot_app, "enrich_findings", fake_enrich)


@pytest.fixture
def ddgs(monkeypatch):
    class Handle:
        calls: list[tuple[str, list[str]]] = []
        result: list[dict] | Exception = []

    def search(query, allowed):
        Handle.calls.append((query, allowed))
        if isinstance(Handle.result, Exception):
            raise Handle.result
        return Handle.result

    Handle.calls = []
    Handle.result = [{"title": "T", "url": "https://sam.gov/f", "excerpt": "found it"}]
    monkeypatch.setattr(nanobot_app, "search_with_ddgs", search)
    return Handle


@pytest.fixture
def client() -> TestClient:
    return TestClient(nanobot_app.app)


def post(client: TestClient, **extra):
    return client.post("/research", json={**BODY, **extra})


def test_agent_urls_become_nanobot_findings(client, spawn, enrich, ddgs) -> None:
    spawn.process = FakeProcess(
        b"SAIC holds it (https://www.usaspending.gov/award/1). See https://sam.gov/opp/2. "
        b"Also https://sam.gov/opp/2 again and https://evil.com/x."
    )
    response = post(client)
    assert response.status_code == 200
    data = response.json()
    assert data["live"] is True
    assert [f["url"] for f in data["findings"]] == ["https://www.usaspending.gov/award/1", "https://sam.gov/opp/2"]
    assert {f["source_mode"] for f in data["findings"]} == {"nanobot"}
    assert all(f["enriched"] for f in data["findings"])
    assert ddgs.calls == []


def test_agent_findings_are_capped_at_five(client, spawn, enrich, ddgs) -> None:
    spawn.process = FakeProcess(" ".join(f"https://sam.gov/opp/{i}" for i in range(9)).encode())
    assert len(post(client).json()["findings"]) == 5


def test_trailing_punctuation_is_stripped_from_urls(client, spawn, enrich, ddgs) -> None:
    spawn.process = FakeProcess(b"See https://sam.gov/opp/1, https://sam.gov/opp/2; and https://sam.gov/opp/3.")
    urls = [f["url"] for f in post(client).json()["findings"]]
    assert urls == ["https://sam.gov/opp/1", "https://sam.gov/opp/2", "https://sam.gov/opp/3"]


def test_markdown_link_urls_are_extracted_cleanly(client, spawn, enrich, ddgs) -> None:
    spawn.process = FakeProcess(b"[the award](https://sam.gov/opp/1) and <https://sam.gov/opp/2>")
    urls = [f["url"] for f in post(client).json()["findings"]]
    assert urls == ["https://sam.gov/opp/1", "https://sam.gov/opp/2"]


def test_summary_joins_title_excerpt_and_url(client, spawn, enrich, ddgs) -> None:
    spawn.process = FakeProcess(b"https://sam.gov/opp/1 https://sam.gov/opp/2")
    summary = post(client).json()["summary"]
    assert summary.count("\n\n") == 1
    assert "(https://sam.gov/opp/1)" in summary and "(https://sam.gov/opp/2)" in summary


def test_agent_command_and_prompt(client, spawn, enrich, ddgs) -> None:
    spawn.process = FakeProcess(b"https://sam.gov/opp/1")
    post(client, audit_feedback={"is_valid": False, "reason": "missing cite"})
    assert spawn.argv[:3] == ("nanobot", "agent", "-m")
    prompt = spawn.argv[3]
    assert QUERY in prompt
    assert "untrusted" in prompt.lower()
    assert "missing cite" in prompt
    assert "site:sam.gov OR site:usaspending.gov" in prompt


def test_caller_supplied_domains_replace_the_default_allowlist(client, spawn, enrich, ddgs) -> None:
    spawn.process = FakeProcess(b"https://dau.edu/guide https://sam.gov/opp/1")
    data = post(client, allowed_domains=["dau.edu"]).json()
    assert [f["url"] for f in data["findings"]] == ["https://dau.edu/guide"]
    assert "site:dau.edu" in spawn.argv[3]
    assert "site:sam.gov" not in spawn.argv[3]


def test_only_off_allowlist_urls_triggers_fallback(client, spawn, enrich, ddgs, caplog) -> None:
    spawn.process = FakeProcess(b"Answer from https://evil.com/x and https://sam.gov.evil.com/y")
    with caplog.at_level(logging.INFO):
        data = post(client).json()
    assert ddgs.calls == [(QUERY, DEFAULT_SITES)]
    assert data["findings"][0]["url"] == "https://sam.gov/f"
    assert "no allowlisted URL" in caplog.text


def test_prose_without_urls_triggers_fallback(client, spawn, enrich, ddgs) -> None:
    spawn.process = FakeProcess(b"SAIC holds the contract, trust me.")
    assert post(client).status_code == 200
    assert len(ddgs.calls) == 1


def test_nonzero_exit_discards_stdout_and_falls_back(client, spawn, enrich, ddgs, caplog) -> None:
    spawn.process = FakeProcess(b"partial https://sam.gov/opp/1", b"context window exceeded", returncode=1)
    with caplog.at_level(logging.WARNING):
        data = post(client).json()
    assert [f["url"] for f in data["findings"]] == ["https://sam.gov/f"]
    assert "exited 1" in caplog.text
    assert "context window exceeded" in caplog.text


def test_timeout_terminates_agent_and_falls_back(client, spawn, enrich, ddgs, monkeypatch, caplog) -> None:
    monkeypatch.setattr(nanobot_app, "AGENT_TIMEOUT_SECONDS", 0.05)
    spawn.process = FakeProcess(hang=True)
    with caplog.at_level(logging.WARNING):
        response = post(client)
    assert response.status_code == 200
    assert spawn.process.terminated is True
    assert len(ddgs.calls) == 1
    assert "timed out" in caplog.text


def test_fallback_findings_are_enriched_and_summarised(client, spawn, enrich, ddgs) -> None:
    spawn.process = FakeProcess(b"no links here")
    data = post(client).json()
    assert data["live"] is True
    assert data["findings"][0]["enriched"] is True
    assert data["summary"] == "T: found it (https://sam.gov/f)"


def test_fallback_with_no_results_is_a_502(client, spawn, enrich, ddgs) -> None:
    spawn.process = FakeProcess(b"")
    ddgs.result = []
    response = post(client)
    assert response.status_code == 502
    assert "no allowlisted source" in response.json()["detail"]


def test_fallback_search_error_is_a_502_naming_only_the_exception_type(client, spawn, enrich, ddgs) -> None:
    spawn.process = FakeProcess(b"")
    ddgs.result = RuntimeError("secret internal detail")
    response = post(client)
    assert response.status_code == 502
    assert "RuntimeError" in response.json()["detail"]
    assert "secret internal detail" not in response.json()["detail"]


def test_fallback_search_timeout_is_a_504(client, spawn, enrich, ddgs, monkeypatch) -> None:
    spawn.process = FakeProcess(b"")
    real_wait_for = asyncio.wait_for

    async def impatient(awaitable, timeout):
        return await real_wait_for(awaitable, 0.01)

    def slow(query, allowed):
        time.sleep(0.3)
        return []

    monkeypatch.setattr(nanobot_app, "search_with_ddgs", slow)
    monkeypatch.setattr(nanobot_app.asyncio, "wait_for", impatient)
    assert post(client).status_code == 504


def test_missing_required_fields_are_rejected(client, spawn) -> None:
    assert client.post("/research", json={"query": QUERY}).status_code == 422
    assert client.post("/research", json={"run_id": "x"}).status_code == 422
    assert spawn.calls == 0


def test_agent_path_end_to_end_with_real_page_fetching(client, spawn, ddgs, respx_mock, monkeypatch) -> None:
    monkeypatch.setattr(nanobot_app, "host_is_public", lambda hostname: True)
    respx_mock.get("https://sam.gov/opp/1").respond(
        200, text="The Cloud One contract is held by SAIC.", headers={"content-type": "text/plain"},
    )
    spawn.process = FakeProcess(b"See https://sam.gov/opp/1")
    finding = post(client).json()["findings"][0]
    assert finding["snippet_only"] is False
    assert finding["http_status"] == 200
    assert "SAIC" in finding["excerpt"]
    assert ddgs.calls == []


def test_search_with_ddgs_filters_caps_and_tags_results(monkeypatch) -> None:
    seen = {}

    class FakeDDGS:
        def text(self, query, max_results):
            seen.update(query=query, max_results=max_results)
            rows = [{"href": "https://evil.com/x", "title": "Off-domain"}]
            rows += [{"href": f"https://sam.gov/opp/{i}.", "title": f"T{i}", "body": "b" * 3000} for i in range(8)]
            return rows

    monkeypatch.setattr(nanobot_app, "DDGS", FakeDDGS)
    findings = nanobot_app.search_with_ddgs("cloud", DEFAULT_SITES)
    assert seen["query"] == "cloud (site:sam.gov OR site:usaspending.gov)"
    assert len(findings) == 5
    assert findings[0]["url"] == "https://sam.gov/opp/0"
    assert all(len(f["excerpt"]) == 1800 for f in findings)
    assert {f["source_mode"] for f in findings} == {"ddgs_fallback"}
    assert all(f["snippet_only"] is True for f in findings)


def test_search_with_ddgs_handles_alternate_row_shapes(monkeypatch) -> None:
    class FakeDDGS:
        def text(self, query, max_results):
            return [{"url": "https://sam.gov/a", "snippet": "via url+snippet keys"}, {"href": ""}, {}]

    monkeypatch.setattr(nanobot_app, "DDGS", FakeDDGS)
    findings = nanobot_app.search_with_ddgs("q", ["sam.gov"])
    assert len(findings) == 1
    assert findings[0]["excerpt"] == "via url+snippet keys"
    assert findings[0]["title"] == "sam.gov"


def test_same_url_with_and_without_trailing_punctuation_is_one_finding(client, spawn, enrich, ddgs) -> None:
    spawn.process = FakeProcess(b"First https://sam.gov/opp/1. Again https://sam.gov/opp/1")
    assert [f["url"] for f in post(client).json()["findings"]] == ["https://sam.gov/opp/1"]


async def test_stop_process_is_a_noop_for_an_exited_process() -> None:
    process = FakeProcess(returncode=0)
    await nanobot_app.stop_process(process)
    assert not process.terminated and not process.killed


async def test_stop_process_kills_when_terminate_is_ignored(monkeypatch) -> None:
    class Stubborn(FakeProcess):
        def terminate(self) -> None:
            self.terminated = True  # ignores SIGTERM: returncode stays None

        async def wait(self) -> int:
            if not self.killed:
                await asyncio.sleep(3600)
            return self.returncode

    real_wait_for = asyncio.wait_for
    monkeypatch.setattr(nanobot_app.asyncio, "wait_for", lambda aw, timeout: real_wait_for(aw, 0.01))
    process = Stubborn(hang=True)
    await nanobot_app.stop_process(process)
    assert process.terminated and process.killed


async def test_cancelled_request_stops_the_agent_process(monkeypatch) -> None:
    process = FakeProcess(hang=True)

    async def create(*argv, **kwargs):
        return process

    monkeypatch.setattr(nanobot_app.asyncio, "create_subprocess_exec", create)
    task = asyncio.create_task(nanobot_app.research(nanobot_app.ResearchRequest(**BODY)))
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert process.terminated is True
