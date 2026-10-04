from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from app.config import Settings
from app.schemas import ReviewDecision
from app.slack.bolt_app import SlackRuntime, interrupt_payload, progress_bar, scope_line

PDF_URL = "https://files.slack.test/download/guide.pdf"


class FakeRepository:
    def __init__(self, run_id: str | None = "run-1") -> None:
        self.run_id = run_id
        self.created: list[dict[str, Any]] = []
        self.updates: list[dict[str, Any]] = []

    async def create_run(self, **kwargs):
        self.created.append(kwargs)
        return self.run_id

    async def update_run(self, run_id, **fields) -> None:
        self.updates.append({"run_id": run_id, **fields})


class FakeGraph:
    def __init__(self, result: dict | Exception | None = None) -> None:
        self.result = result if result is not None else {"final_answer": "the answer"}
        self.started: list[dict] = []
        self.resumed: list[tuple[str, ReviewDecision]] = []

    async def start(self, state):
        self.started.append(state)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result

    async def resume(self, thread_id, decision):
        self.resumed.append((thread_id, decision))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class FakeIngestion:
    def __init__(self, result: dict | Exception | None = None, progress: list[tuple] | None = None) -> None:
        self.result = result or {"duplicate": False, "page_count": 3, "chunks": 7}
        self.progress = progress or []
        self.calls: list[dict[str, Any]] = []
        self.seen_files: list[bytes] = []

    async def ingest_path(self, path, **kwargs):
        self.calls.append({"path": path, **kwargs})
        self.seen_files.append(path.read_bytes())
        for step in self.progress:
            await kwargs["on_progress"](*step)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class FakeSlackClient:
    def __init__(self, metadata: dict | None = None) -> None:
        self.metadata = metadata if metadata is not None else {
            "mimetype": "application/pdf", "name": "guide.pdf", "size": 100,
            "url_private_download": PDF_URL, "channels": ["C-from-file"],
        }
        self.posts: list[dict] = []
        self.updates: list[dict] = []
        self.files_requested: list[str] = []

    async def files_info(self, file):
        self.files_requested.append(file)
        return {"file": self.metadata}

    async def chat_postMessage(self, **kwargs):
        self.posts.append(kwargs)
        return {"ts": "111.222"}

    async def chat_update(self, **kwargs):
        self.updates.append(kwargs)
        return {}

    def texts(self) -> list[str]:
        return [item["text"] for item in self.posts + self.updates]


class Say:
    def __init__(self) -> None:
        self.messages: list[dict] = []

    async def __call__(self, **kwargs) -> None:
        self.messages.append(kwargs)


def runtime(tmp_path, *, repository=None, graph=None, ingestion=None) -> SlackRuntime:
    # Skip __init__: it would open a real Slack connection.
    instance = SlackRuntime.__new__(SlackRuntime)
    instance.settings = Settings(
        app_mode="test", slack_bot_token="xoxb-test-token", slack_app_token="xapp-test",
        document_store=tmp_path / "store",
    )
    instance.repository = repository or FakeRepository()
    instance.graph = graph or FakeGraph()
    instance.ingestion = ingestion or FakeIngestion()
    instance._ingesting = set()
    return instance


async def drain() -> None:
    """Let tasks created with asyncio.create_task run to completion."""
    for _ in range(5):
        await asyncio.sleep(0)
    await asyncio.sleep(0.01)


# --- pure helpers ---------------------------------------------------------------

@pytest.mark.parametrize(("percent", "expected"), [
    (0, "░" * 10), (50, "█" * 5 + "░" * 5), (100, "█" * 10), (-20, "░" * 10), (250, "█" * 10),
])
def test_progress_bar_clamps(percent: int, expected: str) -> None:
    assert progress_bar(percent) == expected


def test_scope_line() -> None:
    assert scope_line({"scope_label": "acme plan"}) == "_Searched only: acme plan_\n"
    assert scope_line({}) == ""


def test_interrupt_payload_handles_objects_dicts_and_none() -> None:
    assert interrupt_payload({}) is None
    assert interrupt_payload({"__interrupt__": []}) is None
    assert interrupt_payload({"__interrupt__": [SimpleNamespace(value={"run_id": "r"})]}) == {"run_id": "r"}
    assert interrupt_payload({"__interrupt__": [{"run_id": "r"}]}) == {"run_id": "r"}


def test_constructor_requires_both_slack_tokens() -> None:
    for tokens in ({}, {"slack_bot_token": "xoxb-1"}, {"slack_app_token": "xapp-1"}):
        with pytest.raises(ValueError, match="Slack tokens are required"):
            SlackRuntime(Settings(app_mode="test", **tokens), None, None, None)


# --- event wiring -----------------------------------------------------------------

class FakeApp:
    def __init__(self) -> None:
        self.events: dict[str, Any] = {}
        self.actions: dict[str, Any] = {}

    def event(self, name):
        return lambda handler: self.events.setdefault(name, handler)

    def action(self, name):
        return lambda handler: self.actions.setdefault(name, handler)


def wired(tmp_path) -> tuple[SlackRuntime, FakeApp, dict[str, list]]:
    instance = runtime(tmp_path)
    instance.app = FakeApp()
    calls: dict[str, list] = {"accept": [], "join": [], "ingest": [], "resume": []}

    async def accept(body, event, say):
        calls["accept"].append(event)

    async def join(event, client):
        calls["join"].append(event)

    async def ingest(event, client):
        calls["ingest"].append(event)

    async def resume(body, client, approved):
        calls["resume"].append(approved)

    instance._accept_message, instance._join_new_channel = accept, join
    instance._ingest_slack_file, instance._resume_review = ingest, resume
    instance._register()
    return instance, instance.app, calls


def test_all_expected_handlers_are_registered(tmp_path) -> None:
    _, app, _ = wired(tmp_path)
    assert set(app.events) == {"app_mention", "message", "file_shared", "channel_created"}
    assert set(app.actions) == {"review_approve", "review_reject"}


async def test_mentions_are_always_accepted(tmp_path) -> None:
    _, app, calls = wired(tmp_path)
    await app.events["app_mention"]({}, {"text": "hi"}, Say())
    assert calls["accept"] == [{"text": "hi"}]


async def test_only_direct_messages_are_accepted_from_the_message_event(tmp_path) -> None:
    _, app, calls = wired(tmp_path)
    await app.events["message"]({}, {"channel_type": "channel", "text": "chatter"}, Say())
    await app.events["message"]({}, {"channel_type": "group", "text": "chatter"}, Say())
    await app.events["message"]({}, {"text": "no type"}, Say())
    assert calls["accept"] == []
    await app.events["message"]({}, {"channel_type": "im", "text": "dm"}, Say())
    assert calls["accept"] == [{"channel_type": "im", "text": "dm"}]


async def test_file_shared_ingests_in_the_background(tmp_path) -> None:
    _, app, calls = wired(tmp_path)
    await app.events["file_shared"]({"file_id": "F1"}, object())
    await drain()
    assert calls["ingest"] == [{"file_id": "F1"}]


async def test_channel_created_is_forwarded(tmp_path) -> None:
    _, app, calls = wired(tmp_path)
    await app.events["channel_created"]({"channel": {"id": "C1"}}, object())
    assert calls["join"] == [{"channel": {"id": "C1"}}]


@pytest.mark.parametrize(("action", "approved"), [("review_approve", True), ("review_reject", False)])
async def test_review_buttons_ack_then_resume(tmp_path, action: str, approved: bool) -> None:
    _, app, calls = wired(tmp_path)
    order: list[str] = []

    async def ack() -> None:
        order.append("ack")
        assert calls["resume"] == []  # Slack must be acknowledged before the slow resume

    await app.actions[action](ack, {}, object())
    assert order == ["ack"] and calls["resume"] == [approved]


# --- accepting questions ----------------------------------------------------------

def message_body(**overrides) -> tuple[dict, dict]:
    body = {"team_id": "T1", "event_id": "Ev1"}
    event = {"channel": "C1", "ts": "100.1", "user": "U1", "text": "<@UBOT> What is a PSM?"}
    event.update(overrides)
    return body, event


async def test_question_starts_a_run_and_answers_in_thread(tmp_path) -> None:
    repository, graph, say = FakeRepository(), FakeGraph(), Say()
    instance = runtime(tmp_path, repository=repository, graph=graph)
    body, event = message_body()
    await instance._accept_message(body, event, say)
    await drain()

    assert repository.created == [{
        "source_event_id": "Ev1", "thread_id": "T1:C1:100.1", "channel_id": "C1",
        "requester_id": "U1", "question": "What is a PSM?",
    }]
    assert graph.started == [{
        "run_id": "run-1", "thread_id": "T1:C1:100.1", "channel_id": "C1",
        "requester_id": "U1", "question": "What is a PSM?",
    }]
    assert say.messages[0]["thread_ts"] == "100.1" and "run-1" in say.messages[0]["text"]
    assert say.messages[1] == {"text": "the answer", "thread_ts": "100.1"}


async def test_replies_in_an_existing_thread_reuse_the_thread_id(tmp_path) -> None:
    repository, say = FakeRepository(), Say()
    body, event = message_body(thread_ts="50.5")
    await runtime(tmp_path, repository=repository)._accept_message(body, event, say)
    await drain()
    assert repository.created[0]["thread_id"] == "T1:C1:50.5"
    assert all(message["thread_ts"] == "50.5" for message in say.messages)


async def test_missing_team_and_user_fall_back_to_unknown(tmp_path) -> None:
    repository = FakeRepository()
    event = {"channel": "C1", "ts": "1.1", "text": "question"}
    await runtime(tmp_path, repository=repository)._accept_message({}, event, Say())
    await drain()
    assert repository.created[0]["thread_id"] == "unknown:C1:1.1"
    assert repository.created[0]["requester_id"] == "unknown"


@pytest.mark.parametrize("overrides", [
    {"bot_id": "B1"},                       # our own and other bots' messages
    {"subtype": "message_changed"},
    {"subtype": "bot_message"},
    {"text": "<@UBOT>"},                    # a bare mention
    {"text": "   "},
    {"text": ""},
])
async def test_ignored_messages_do_not_create_runs(tmp_path, overrides) -> None:
    repository, graph, say = FakeRepository(), FakeGraph(), Say()
    body, event = message_body(**overrides)
    await runtime(tmp_path, repository=repository, graph=graph)._accept_message(body, event, say)
    await drain()
    assert repository.created == [] and graph.started == [] and say.messages == []


async def test_multiple_mentions_are_all_stripped(tmp_path) -> None:
    repository = FakeRepository()
    body, event = message_body(text="<@UBOT> hey <@U2ABC> what is a PSM?")
    await runtime(tmp_path, repository=repository)._accept_message(body, event, Say())
    await drain()
    assert repository.created[0]["question"] == "hey  what is a PSM?"


async def test_redelivered_slack_event_is_dropped(tmp_path) -> None:
    repository, graph, say = FakeRepository(run_id=None), FakeGraph(), Say()
    body, event = message_body()
    await runtime(tmp_path, repository=repository, graph=graph)._accept_message(body, event, say)
    await drain()
    assert graph.started == [] and say.messages == []


async def test_workflow_failure_marks_run_failed_and_tells_the_thread(tmp_path) -> None:
    repository, say = FakeRepository(), Say()
    graph = FakeGraph(RuntimeError("LM Studio unreachable: secret detail"))
    body, event = message_body()
    await runtime(tmp_path, repository=repository, graph=graph)._accept_message(body, event, say)
    await drain()

    (update,) = repository.updates
    assert update["status"] == "failed" and update["error_code"] == "slack_workflow_failure"
    assert "RuntimeError" in update["error_message"]
    failure = say.messages[-1]
    assert "RuntimeError" in failure["text"] and failure["thread_ts"] == "100.1"
    assert "secret detail" not in failure["text"]


# --- delivering results ------------------------------------------------------------

def review_result(**extra) -> dict:
    return {
        "thread_id": "T1:C1:100.1",
        "__interrupt__": [SimpleNamespace(value={
            "run_id": "run-9", "draft": "Draft body [Guide.pdf, p. 3]",
            "risk_breakdown": {"total": 80},
        })],
        **extra,
    }


async def test_interrupt_posts_review_card_with_both_buttons(tmp_path) -> None:
    say = Say()
    await runtime(tmp_path)._deliver_result(review_result(), "C1", "100.1", say)

    (message,) = say.messages
    assert message["thread_ts"] == "100.1"
    assert "80" in message["text"]
    section, actions = message["blocks"]
    assert "80/100" in section["text"]["text"] and "Draft body" in section["text"]["text"]
    approve, reject = actions["elements"]
    assert (approve["action_id"], approve["style"]) == ("review_approve", "primary")
    assert (reject["action_id"], reject["style"]) == ("review_reject", "danger")
    assert json.loads(approve["value"]) == {
        "run_id": "run-9", "thread_id": "T1:C1:100.1", "channel": "C1", "thread_ts": "100.1",
    }
    assert approve["value"] == reject["value"]


async def test_review_card_shows_the_search_scope(tmp_path) -> None:
    say = Say()
    await runtime(tmp_path)._deliver_result(review_result(scope_label="acme plan"), "C1", "1.1", say)
    assert "_Searched only: acme plan_" in say.messages[0]["blocks"][0]["text"]["text"]


async def test_review_card_survives_a_payload_without_risk_data(tmp_path) -> None:
    say = Say()
    result = {"__interrupt__": [{"run_id": "r", "draft": "d"}]}
    await runtime(tmp_path)._deliver_result(result, "C1", "1.1", say)
    assert "0/100" in say.messages[0]["blocks"][0]["text"]["text"]


async def test_final_answer_is_posted_with_scope_line(tmp_path) -> None:
    say = Say()
    await runtime(tmp_path)._deliver_result(
        {"final_answer": "42", "scope_label": "acme plan"}, "C1", "1.1", say,
    )
    assert say.messages == [{"text": "_Searched only: acme plan_\n42", "thread_ts": "1.1"}]


async def test_result_with_nothing_to_deliver_posts_nothing(tmp_path) -> None:
    say = Say()
    await runtime(tmp_path)._deliver_result({}, "C1", "1.1", say)
    await runtime(tmp_path)._deliver_result({"final_answer": ""}, "C1", "1.1", say)
    assert say.messages == []


# --- resuming reviews --------------------------------------------------------------

def button_body(user: str | None = "UREV") -> dict:
    value = json.dumps({"run_id": "run-9", "thread_id": "T1:C1:100.1", "channel": "C1", "thread_ts": "100.1"})
    body: dict[str, Any] = {"actions": [{"value": value}]}
    if user:
        body["user"] = {"id": user}
    return body


async def test_approve_resumes_the_checkpoint_and_posts_the_answer(tmp_path) -> None:
    graph, client = FakeGraph({"final_answer": "approved answer"}), FakeSlackClient()
    await runtime(tmp_path, graph=graph)._resume_review(button_body(), client, approved=True)

    (thread_id, decision), = graph.resumed
    assert thread_id == "T1:C1:100.1"
    assert (decision.approved, decision.reviewer_id, decision.note) == (True, "UREV", None)
    assert client.posts == [{"channel": "C1", "text": "approved answer", "thread_ts": "100.1"}]


async def test_reject_resumes_with_a_revision_note(tmp_path) -> None:
    graph, client = FakeGraph({"final_answer": "x"}), FakeSlackClient()
    await runtime(tmp_path, graph=graph)._resume_review(button_body(), client, approved=False)
    (_, decision), = graph.resumed
    assert (decision.approved, decision.note) == (False, "Reviewer requested revision")


async def test_reject_that_triggers_another_review_posts_a_new_card(tmp_path) -> None:
    graph, client = FakeGraph(review_result()), FakeSlackClient()
    await runtime(tmp_path, graph=graph)._resume_review(button_body(), client, approved=False)
    (post,) = client.posts
    assert post["channel"] == "C1" and post["thread_ts"] == "100.1" and "blocks" in post


async def test_unknown_reviewer_falls_back_to_unknown(tmp_path) -> None:
    graph = FakeGraph()
    await runtime(tmp_path, graph=graph)._resume_review(button_body(user=None), FakeSlackClient(), approved=True)
    assert graph.resumed[0][1].reviewer_id == "unknown"


# --- PDF uploads ---------------------------------------------------------------------

def store_is_clean(tmp_path) -> bool:
    store = tmp_path / "store"
    return not store.exists() or not list(store.iterdir())


async def test_pdf_upload_is_downloaded_ingested_and_reported(tmp_path, respx_mock) -> None:
    route = respx_mock.get(PDF_URL).respond(200, content=b"%PDF-fake-bytes")
    ingestion, client = FakeIngestion(), FakeSlackClient()
    instance = runtime(tmp_path, ingestion=ingestion)
    await instance._ingest_slack_file({"file_id": "F1", "channel_id": "C1"}, client)

    assert route.calls.last.request.headers["authorization"] == "Bearer xoxb-test-token"
    (call,) = ingestion.calls
    assert ingestion.seen_files == [b"%PDF-fake-bytes"]
    assert call["slack_file_id"] == "F1" and call["slack_channel_id"] == "C1"
    assert call["display_filename"] == "guide.pdf"
    assert client.files_requested == ["F1"]
    assert "downloading" in client.posts[0]["text"] and client.posts[0]["channel"] == "C1"
    assert "Ingested `guide.pdf` — 3 pages, 7 chunks" in client.updates[-1]["text"]
    assert len(client.posts) == 1  # one status message, edited in place
    assert instance._ingesting == set()
    assert store_is_clean(tmp_path)


async def test_duplicate_pdf_is_reported_as_already_in_the_library(tmp_path, respx_mock) -> None:
    respx_mock.get(PDF_URL).respond(200, content=b"%PDF")
    client = FakeSlackClient()
    await runtime(tmp_path, ingestion=FakeIngestion({"duplicate": True})).\
        _ingest_slack_file({"file_id": "F1", "channel_id": "C1"}, client)
    assert "already in the library" in client.updates[-1]["text"]


async def test_upload_filename_is_reduced_to_its_basename(tmp_path, respx_mock) -> None:
    respx_mock.get(PDF_URL).respond(200, content=b"%PDF")
    ingestion = FakeIngestion()
    client = FakeSlackClient({
        "mimetype": "application/pdf", "name": "../../etc/evil.pdf", "size": 10,
        "url_private_download": PDF_URL,
    })
    await runtime(tmp_path, ingestion=ingestion)._ingest_slack_file({"file_id": "F1", "channel_id": "C1"}, client)
    assert ingestion.calls[0]["display_filename"] == "evil.pdf"


async def test_missing_filename_defaults_to_upload_pdf(tmp_path, respx_mock) -> None:
    respx_mock.get(PDF_URL).respond(200, content=b"%PDF")
    ingestion = FakeIngestion()
    client = FakeSlackClient({"mimetype": "application/pdf", "url_private_download": PDF_URL})
    await runtime(tmp_path, ingestion=ingestion)._ingest_slack_file({"file_id": "F1", "channel_id": "C1"}, client)
    assert ingestion.calls[0]["display_filename"] == "upload.pdf"


async def test_progress_updates_edit_the_status_message_and_are_throttled(tmp_path, respx_mock) -> None:
    respx_mock.get(PDF_URL).respond(200, content=b"%PDF")
    ingestion = FakeIngestion(progress=[
        ("parsing", 0, 0, 5),
        ("embedding", 0, 100, 20), ("embedding", 10, 100, 27), ("embedding", 20, 100, 35),
        ("storing", 0, 0, 95),
    ])
    client = FakeSlackClient()
    await runtime(tmp_path, ingestion=ingestion)._ingest_slack_file({"file_id": "F1", "channel_id": "C1"}, client)

    progress = [text for text in client.texts() if "░" in text or "█" in text]
    assert len(progress) == 3  # parsing, first embedding tick, storing; rapid repeats are dropped
    assert "embedding 0/100 chunks" in progress[1]
    assert all(update["ts"] == "111.222" for update in client.updates)


@pytest.mark.parametrize("metadata", [
    {"mimetype": "image/png", "name": "a.png", "url_private_download": PDF_URL},
    {"mimetype": "text/plain", "name": "a.txt", "url_private_download": PDF_URL},
    {"name": "mystery", "url_private_download": PDF_URL},
])
async def test_non_pdf_uploads_are_silently_ignored(tmp_path, metadata) -> None:
    ingestion, client = FakeIngestion(), FakeSlackClient(metadata)
    instance = runtime(tmp_path, ingestion=ingestion)
    await instance._ingest_slack_file({"file_id": "F1", "channel_id": "C1"}, client)
    assert ingestion.calls == [] and client.posts == [] and instance._ingesting == set()


async def test_event_without_file_id_is_ignored(tmp_path) -> None:
    client = FakeSlackClient()
    await runtime(tmp_path)._ingest_slack_file({"channel_id": "C1"}, client)
    assert client.files_requested == []


async def test_file_already_being_ingested_is_skipped(tmp_path) -> None:
    instance, client = runtime(tmp_path), FakeSlackClient()
    instance._ingesting.add("F1")
    await instance._ingest_slack_file({"file_id": "F1", "channel_id": "C1"}, client)
    assert client.files_requested == [] and instance._ingesting == {"F1"}


async def test_channel_falls_back_to_the_files_own_channels(tmp_path, respx_mock) -> None:
    respx_mock.get(PDF_URL).respond(200, content=b"%PDF")
    ingestion, client = FakeIngestion(), FakeSlackClient()
    await runtime(tmp_path, ingestion=ingestion)._ingest_slack_file({"file_id": "F1"}, client)
    assert client.posts[0]["channel"] == "C-from-file"
    assert ingestion.calls[0]["slack_channel_id"] == "C-from-file"


async def test_upload_with_no_known_channel_still_ingests_without_posting(tmp_path, respx_mock) -> None:
    respx_mock.get(PDF_URL).respond(200, content=b"%PDF")
    ingestion = FakeIngestion()
    client = FakeSlackClient({"mimetype": "application/pdf", "name": "a.pdf", "url_private_download": PDF_URL})
    await runtime(tmp_path, ingestion=ingestion)._ingest_slack_file({"file_id": "F1"}, client)
    assert len(ingestion.calls) == 1 and client.posts == [] and client.updates == []


async def test_declared_size_over_50_mb_fails_before_downloading(tmp_path, respx_mock) -> None:
    route = respx_mock.get(PDF_URL).respond(200, content=b"%PDF")
    client = FakeSlackClient({
        "mimetype": "application/pdf", "name": "big.pdf", "size": 50 * 1024 * 1024 + 1,
        "url_private_download": PDF_URL,
    })
    ingestion = FakeIngestion()
    instance = runtime(tmp_path, ingestion=ingestion)
    await instance._ingest_slack_file({"file_id": "F1", "channel_id": "C1"}, client)
    assert not route.called and ingestion.calls == []
    assert "ValueError" in client.posts[-1]["text"] and "failed safely" in client.posts[-1]["text"]
    assert instance._ingesting == set()


async def test_streamed_body_over_50_mb_fails_even_if_metadata_lied(tmp_path, respx_mock) -> None:
    respx_mock.get(PDF_URL).respond(200, content=b"x" * (50 * 1024 * 1024 + 1))
    ingestion, client = FakeIngestion(), FakeSlackClient()  # metadata claims size=100
    await runtime(tmp_path, ingestion=ingestion)._ingest_slack_file({"file_id": "F1", "channel_id": "C1"}, client)
    assert ingestion.calls == []
    assert "ValueError" in client.posts[-1]["text"]
    assert store_is_clean(tmp_path)


async def test_download_http_error_is_reported_safely(tmp_path, respx_mock) -> None:
    respx_mock.get(PDF_URL).respond(403)
    ingestion, client = FakeIngestion(), FakeSlackClient()
    await runtime(tmp_path, ingestion=ingestion)._ingest_slack_file({"file_id": "F1", "channel_id": "C1"}, client)
    assert ingestion.calls == []
    assert "HTTPStatusError" in client.posts[-1]["text"]
    assert store_is_clean(tmp_path)


async def test_network_error_is_reported_safely(tmp_path, respx_mock) -> None:
    respx_mock.get(PDF_URL).mock(side_effect=httpx.ConnectError("refused"))
    client = FakeSlackClient()
    await runtime(tmp_path)._ingest_slack_file({"file_id": "F1", "channel_id": "C1"}, client)
    assert "ConnectError" in client.posts[-1]["text"]


async def test_ingestion_failure_is_reported_cleans_up_and_releases_the_file(tmp_path, respx_mock) -> None:
    respx_mock.get(PDF_URL).respond(200, content=b"%PDF")
    ingestion = FakeIngestion(ValueError("PDF requires a password"))
    client = FakeSlackClient()
    instance = runtime(tmp_path, ingestion=ingestion)
    await instance._ingest_slack_file({"file_id": "F1", "channel_id": "C1"}, client)
    assert client.posts[-1]["text"] == ":x: PDF ingestion failed safely: `ValueError`."
    assert "password" not in client.posts[-1]["text"]
    assert instance._ingesting == set()
    assert store_is_clean(tmp_path)


async def test_a_file_can_be_ingested_again_after_a_failure(tmp_path, respx_mock) -> None:
    respx_mock.get(PDF_URL).respond(200, content=b"%PDF")
    ingestion = FakeIngestion(ValueError("boom"))
    instance, client = runtime(tmp_path, ingestion=ingestion), FakeSlackClient()
    await instance._ingest_slack_file({"file_id": "F1", "channel_id": "C1"}, client)
    ingestion.result = {"duplicate": False, "page_count": 1, "chunks": 1}
    await instance._ingest_slack_file({"file_id": "F1", "channel_id": "C1"}, client)
    assert len(ingestion.calls) == 2


async def test_failure_with_no_known_channel_does_not_raise(tmp_path) -> None:
    client = FakeSlackClient({"mimetype": "application/pdf", "size": 10 ** 9, "url_private_download": PDF_URL})
    await runtime(tmp_path)._ingest_slack_file({"file_id": "F1"}, client)
    assert client.posts == []
