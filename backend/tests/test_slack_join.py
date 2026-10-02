from __future__ import annotations

import pytest

from app.config import Settings
from app.slack.bolt_app import WELCOME_TEXT, SlackRuntime


class FakeClient:
    def __init__(self, fail_join: bool = False) -> None:
        self.joined: list[str] = []
        self.posts: list[dict] = []
        self.fail_join = fail_join

    async def conversations_join(self, channel: str):
        if self.fail_join:
            raise RuntimeError("missing_scope")
        self.joined.append(channel)

    async def chat_postMessage(self, **kwargs):
        self.posts.append(kwargs)


def runtime(auto_join: bool = True) -> SlackRuntime:
    # Skip __init__: it would open a real Slack connection.
    instance = SlackRuntime.__new__(SlackRuntime)
    instance.settings = Settings(app_mode="test", slack_auto_join=auto_join)
    return instance


@pytest.mark.asyncio
async def test_joins_new_channel_and_says_hello() -> None:
    client = FakeClient()
    await runtime()._join_new_channel({"channel": {"id": "C123", "name": "demo-1"}}, client)
    assert client.joined == ["C123"]
    assert client.posts == [{"channel": "C123", "text": WELCOME_TEXT}]


@pytest.mark.asyncio
async def test_auto_join_can_be_disabled() -> None:
    client = FakeClient()
    await runtime(auto_join=False)._join_new_channel({"channel": {"id": "C123"}}, client)
    assert client.joined == [] and client.posts == []


@pytest.mark.asyncio
async def test_join_failure_is_swallowed_and_no_hello_is_posted() -> None:
    client = FakeClient(fail_join=True)
    await runtime()._join_new_channel({"channel": {"id": "C123"}}, client)
    assert client.posts == []


@pytest.mark.asyncio
async def test_malformed_event_is_ignored() -> None:
    client = FakeClient()
    await runtime()._join_new_channel({}, client)
    assert client.joined == []
