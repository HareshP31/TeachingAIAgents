from types import SimpleNamespace

from app.services.llm import message_text


def test_message_text_prefers_content() -> None:
    message = SimpleNamespace(
        content="answer",
        model_extra={"reasoning_content": "hidden"},
    )
    assert message_text(message) == "answer"


def test_message_text_falls_back_to_reasoning_content() -> None:
    message = SimpleNamespace(
        content="",
        model_extra={"reasoning_content": '{"status":"ok"}'},
    )
    assert message_text(message) == '{"status":"ok"}'
