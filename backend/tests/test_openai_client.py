from types import SimpleNamespace

from app.core.config import Settings
from app.services.openai_client import OpenAIWorkflowClient


def make_client(*, stream: bool) -> OpenAIWorkflowClient:
    return OpenAIWorkflowClient(
        Settings(
            openai_api_key="test-key",
            openai_stream=stream,
        )
    )


def test_chat_json_uses_streaming_when_enabled():
    client = make_client(stream=True)
    calls: list[dict[str, object]] = []

    def create(**kwargs):
        calls.append(kwargs)
        return [
            SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content='{"items":'))]),
            SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="[]"))]),
            SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="}"))]),
        ]

    client.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))

    result = client.generate_json(system="system", user="user", schema_name="test_schema")

    assert result == {"items": []}
    assert calls[0]["stream"] is True
    assert calls[0]["response_format"] == {"type": "json_object"}


def test_chat_json_can_disable_streaming():
    client = make_client(stream=False)
    calls: list[dict[str, object]] = []

    def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{"ok": true}'))])

    client.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))

    result = client.generate_json(system="system", user="user", schema_name="test_schema")

    assert result == {"ok": True}
    assert "stream" not in calls[0]
