from __future__ import annotations

import asyncio
import json
import re
import tempfile
from pathlib import Path

import httpx
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
from slack_bolt.async_app import AsyncApp

from app.config import Settings
from app.db.repository import Repository
from app.graphs.conversation_graph import ConversationGraph
from app.graphs.ingestion_graph import IngestionService
from app.schemas import ConversationState, ReviewDecision


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
            await say(
                thread_ts=thread_ts, text=f"Human review required. Risk score: {risk.get('total', 0)}",
                blocks=[
                    {"type": "section", "text": {"type": "mrkdwn", "text":
                        f"*Human review required* — risk `{risk.get('total', 0)}/100`\n\n{payload.get('draft', '')}"}},
                    {"type": "actions", "elements": [
                        {"type": "button", "text": {"type": "plain_text", "text": "Approve"},
                         "style": "primary", "action_id": "review_approve", "value": value},
                        {"type": "button", "text": {"type": "plain_text", "text": "Reject"},
                         "style": "danger", "action_id": "review_reject", "value": value},
                    ]},
                ],
            )
        elif result.get("final_answer"):
            await say(text=result["final_answer"], thread_ts=thread_ts)

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
        if not file_id:
            return
        temporary: Path | None = None
        try:
            metadata = (await client.files_info(file=file_id))["file"]
            conversations = metadata.get("channels") or metadata.get("groups") or metadata.get("ims") or []
            channel = conversations[0] if conversations else None
            if metadata.get("mimetype") != "application/pdf":
                return
            if int(metadata.get("size") or 0) > 50 * 1024 * 1024:
                raise ValueError("PDF exceeds the 50 MB limit")
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
            result = await self.ingestion.ingest_path(
                temporary, slack_file_id=file_id,
                display_filename=Path(metadata.get("name", "upload.pdf")).name,
            )
            if channel:
                await client.chat_postMessage(
                    channel=channel,
                    text=f"Ingested `{metadata.get('name')}` ({result.get('chunks', 0)} chunks).",
                )
        except Exception as exc:
            if "channel" in locals() and channel:
                await client.chat_postMessage(
                    channel=channel, text=f"PDF ingestion failed safely: `{type(exc).__name__}`.",
                )
        finally:
            if temporary:
                temporary.unlink(missing_ok=True)
