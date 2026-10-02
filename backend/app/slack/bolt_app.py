from __future__ import annotations

import asyncio
import json
import logging
import re
import tempfile
import time
from pathlib import Path

import httpx
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
from slack_bolt.async_app import AsyncApp

from app.config import Settings
from app.db.repository import Repository
from app.graphs.conversation_graph import ConversationGraph
from app.graphs.ingestion_graph import IngestionService
from app.schemas import ConversationState, ReviewDecision
from app.services.progress import progress_label

logger = logging.getLogger(__name__)
PROGRESS_INTERVAL_SECONDS = 4.0
WELCOME_TEXT = (
    ":wave: I've joined this channel automatically. Drop a PDF here to add it to the shared "
    "library, or @mention me with a question. To ask about a file you just added, say "
    "\"the document I just uploaded\"."
)


def progress_bar(percent: int, width: int = 10) -> str:
    filled = round(width * max(0, min(percent, 100)) / 100)
    return "█" * filled + "░" * (width - filled)


def scope_line(result: dict) -> str:
    label = result.get("scope_label")
    return f"_Searched only: {label}_\n" if label else ""


def interrupt_payload(result: dict) -> dict | None:
    interrupts = result.get("__interrupt__")
    if not interrupts:
        return None
    item = interrupts[0]
    return item.value if hasattr(item, "value") else item


class SlackRuntime:
    def __init__(
        self, settings: Settings, repository: Repository, graph: ConversationGraph,
        ingestion: IngestionService,
    ) -> None:
        if not settings.slack_bot_token or not settings.slack_app_token:
            raise ValueError("Slack tokens are required when SLACK_ENABLED=true")
        self.settings = settings
        self.repository = repository
        self.graph = graph
        self.ingestion = ingestion
        self.app = AsyncApp(token=settings.slack_bot_token)
        self.handler = AsyncSocketModeHandler(self.app, settings.slack_app_token)
        self.task: asyncio.Task | None = None
        self._ingesting: set[str] = set()
        self._register()

    def _register(self) -> None:
        @self.app.event("app_mention")
        async def mention(body, event, say):
            await self._accept_message(body, event, say)

        @self.app.event("message")
        async def direct_message(body, event, say):
            if event.get("channel_type") == "im":
                await self._accept_message(body, event, say)

        @self.app.event("file_shared")
        async def file_shared(event, client):
            asyncio.create_task(self._ingest_slack_file(event, client))

        @self.app.event("channel_created")
        async def channel_created(event, client):
            await self._join_new_channel(event, client)

        @self.app.action("review_approve")
        async def approve(ack, body, client):
            await ack()
            await self._resume_review(body, client, approved=True)

        @self.app.action("review_reject")
        async def reject(ack, body, client):
            await ack()
            await self._resume_review(body, client, approved=False)

    async def start(self) -> None:
        self.task = asyncio.create_task(self.handler.start_async())

    async def stop(self) -> None:
        await self.handler.close_async()
        if self.task:
            self.task.cancel()

    async def _join_new_channel(self, event: dict, client) -> None:
        """Join newly created public channels so nobody has to /invite the bot.

        Needs the channels:join and channels:read scopes. Private channels cannot be
        joined this way; a member still has to invite the bot there.
        """
        if not self.settings.slack_auto_join:
            return
        channel = (event.get("channel") or {}).get("id")
        if not channel:
            return
        try:
            await client.conversations_join(channel=channel)
        except Exception:  # noqa: BLE001 - most likely a missing scope; never crash the listener
            logger.warning(
                "Could not auto-join channel %s; check the channels:join scope and reinstall the app",
                channel, exc_info=True,
            )
            return
        try:
            await client.chat_postMessage(channel=channel, text=WELCOME_TEXT)
        except Exception:  # noqa: BLE001
            logger.warning("Joined %s but could not post the welcome message", channel, exc_info=True)

    async def _accept_message(self, body: dict, event: dict, say) -> None:
        if event.get("bot_id") or event.get("subtype"):
            return
        question = re.sub(r"<@[A-Z0-9]+>", "", event.get("text", "")).strip()
        if not question:
            return
        channel = event["channel"]
        thread_ts = event.get("thread_ts") or event["ts"]
        graph_thread = f"{body.get('team_id', 'unknown')}:{channel}:{thread_ts}"
        run_id = await self.repository.create_run(
            source_event_id=body.get("event_id"), thread_id=graph_thread,
            channel_id=channel, requester_id=event.get("user", "unknown"), question=question,
        )
        if run_id is None:
            return
        await say(text=f"Starting audited run `{run_id}`…", thread_ts=thread_ts)
        state: ConversationState = {
            "run_id": str(run_id), "thread_id": graph_thread, "channel_id": channel,
            "requester_id": event.get("user", "unknown"), "question": question,
        }
        asyncio.create_task(self._run_and_respond(state, channel, thread_ts, say))

    async def _run_and_respond(self, state: ConversationState, channel: str, thread_ts: str, say) -> None:
        try:
            result = await self.graph.start(state)
            await self._deliver_result(result, channel, thread_ts, say)
        except Exception as exc:
            await self.repository.update_run(
                state["run_id"], status="failed", error_code="slack_workflow_failure",
                error_message=f"{type(exc).__name__}: {exc}"[:500],
            )
            await say(text=f"Run failed safely: `{type(exc).__name__}`. Check the dashboard.", thread_ts=thread_ts)

    async def _deliver_result(self, result: dict, channel: str, thread_ts: str, say) -> None:
        payload = interrupt_payload(result)
        if payload:
            value = json.dumps({
                "run_id": payload["run_id"], "thread_id": result.get("thread_id"),
                "channel": channel, "thread_ts": thread_ts,
            })
            risk = payload.get("risk_breakdown", {})
            scope = scope_line(result)
            await say(
                thread_ts=thread_ts, text=f"Human review required. Risk score: {risk.get('total', 0)}",
                blocks=[
                    {"type": "section", "text": {"type": "mrkdwn", "text":
                        f"*Human review required* — risk `{risk.get('total', 0)}/100`\n{scope}\n{payload.get('draft', '')}"}},
                    {"type": "actions", "elements": [
                        {"type": "button", "text": {"type": "plain_text", "text": "Approve"},
                         "style": "primary", "action_id": "review_approve", "value": value},
                        {"type": "button", "text": {"type": "plain_text", "text": "Reject"},
                         "style": "danger", "action_id": "review_reject", "value": value},
                    ]},
                ],
            )
        elif result.get("final_answer"):
            await say(text=f"{scope_line(result)}{result['final_answer']}", thread_ts=thread_ts)

    async def _resume_review(self, body: dict, client, approved: bool) -> None:
        data = json.loads(body["actions"][0]["value"])
        result = await self.graph.resume(data["thread_id"], ReviewDecision(
            approved=approved, reviewer_id=body.get("user", {}).get("id", "unknown"),
            note=None if approved else "Reviewer requested revision",
        ))

        async def say(**kwargs):
            await client.chat_postMessage(channel=data["channel"], **kwargs)

        await self._deliver_result(result, data["channel"], data["thread_ts"], say)

    async def _ingest_slack_file(self, event: dict, client) -> None:
        file_id = event.get("file_id")
        if not file_id or file_id in self._ingesting:
            return
        self._ingesting.add(file_id)
        temporary: Path | None = None
        channel: str | None = event.get("channel_id")
        status_ts: str | None = None
        try:
            metadata = (await client.files_info(file=file_id))["file"]
            if metadata.get("mimetype") != "application/pdf":
                return
            if not channel:
                conversations = metadata.get("channels") or metadata.get("groups") or metadata.get("ims") or []
                channel = conversations[0] if conversations else None
            name = metadata.get("name") or "upload.pdf"
            if int(metadata.get("size") or 0) > 50 * 1024 * 1024:
                raise ValueError("PDF exceeds the 50 MB limit")

            async def post(text: str) -> None:
                nonlocal status_ts
                if not channel:
                    return
                if status_ts is None:
                    status_ts = (await client.chat_postMessage(channel=channel, text=text)).get("ts")
                else:
                    await client.chat_update(channel=channel, ts=status_ts, text=text)

            await post(f":inbox_tray: Received `{name}` — downloading…")
            self.settings.document_store.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                dir=self.settings.document_store, suffix=".pdf", delete=False,
            ) as handle:
                temporary = Path(handle.name)
            async with httpx.AsyncClient(timeout=60) as http:
                async with http.stream(
                    "GET",
                    metadata["url_private_download"],
                    headers={"Authorization": f"Bearer {self.settings.slack_bot_token}"},
                ) as response:
                    response.raise_for_status()
                    total = 0
                    with temporary.open("wb") as handle:
                        async for block in response.aiter_bytes():
                            total += len(block)
                            if total > 50 * 1024 * 1024:
                                raise ValueError("PDF exceeds the 50 MB limit")
                            handle.write(block)

            last_update = 0.0
            last_stage = ""

            async def on_progress(stage: str, done: int, total: int, percent: int) -> None:
                # Slack rate-limits message edits, so update on stage changes
                # and otherwise at most every few seconds.
                nonlocal last_update, last_stage
                now = time.monotonic()
                if stage == last_stage and now - last_update < PROGRESS_INTERVAL_SECONDS:
                    return
                last_update, last_stage = now, stage
                await post(
                    f":gear: `{name}` — {progress_bar(percent)} {percent}% · "
                    f"{progress_label(stage, done, total)}"
                )

            result = await self.ingestion.ingest_path(
                temporary, slack_file_id=file_id, display_filename=Path(name).name,
                slack_channel_id=channel, on_progress=on_progress,
            )
            if result.get("duplicate"):
                await post(
                    f":white_check_mark: `{name}` is already in the library, so nothing was "
                    "re-ingested. Ask about it with \"the document I just uploaded\"."
                )
            else:
                await post(
                    f":white_check_mark: Ingested `{name}` — {result.get('page_count', '?')} pages, "
                    f"{result.get('chunks', 0)} chunks. It's now in the shared library, searchable "
                    "from every channel. Ask about it with \"the document I just uploaded\"."
                )
        except Exception as exc:
            logger.exception("Slack PDF ingestion failed for %s", file_id)
            if channel:
                await client.chat_postMessage(
                    channel=channel, text=f":x: PDF ingestion failed safely: `{type(exc).__name__}`.",
                )
        finally:
            self._ingesting.discard(file_id)
            if temporary:
                temporary.unlink(missing_ok=True)
