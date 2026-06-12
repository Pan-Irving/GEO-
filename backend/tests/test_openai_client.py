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


def test_chat_markdown_does_not_force_json_response_format():
    client = make_client(stream=False)
    calls: list[dict[str, object]] = []

    def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="# Brief\n\n正文"))])

    client.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))

    result = client.generate_markdown(system="system", user="user", schema_name="geo_brief")

    assert result == {"title": "geo_brief", "markdown": "# Brief\n\n正文"}
    assert "response_format" not in calls[0]
    assert "stream" not in calls[0]


def test_streaming_chat_markdown_does_not_force_json_response_format():
    client = make_client(stream=True)
    calls: list[dict[str, object]] = []

    def create(**kwargs):
        calls.append(kwargs)
        return [
            SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="# 正文"))]),
            SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="\n\n内容"))]),
        ]

    client.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))

    text = client.generate_text(system="system", user="user")

    assert text == "# 正文\n\n内容"
    assert calls[0]["stream"] is True
    assert "response_format" not in calls[0]


def test_planning_profile_uses_planning_api_config():
    client = OpenAIWorkflowClient(
        Settings(
            openai_api_key="writing-key",
            openai_base_url="https://writing.example/v1",
            openai_model="gpt-writing",
            openai_stream=False,
            planning_api_key="planning-key",
            planning_base_url="https://api.deepseek.com",
            planning_model="deepseek-v4-pro",
            planning_stream=True,
            planning_timeout_seconds=120,
        ),
        profile="planning",
    )

    calls: list[dict[str, object]] = []

    def create(**kwargs):
        calls.append(kwargs)
        return [
            SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content='{"ok":'))]),
            SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="true}"))]),
        ]

    client.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))

    result = client.generate_json(system="system", user="user", schema_name="test_schema")

    assert result == {"ok": True}
    assert client.model == "deepseek-v4-pro"
    assert calls[0]["model"] == "deepseek-v4-pro"
    assert calls[0]["stream"] is True


def test_planning_profile_falls_back_to_default_config_without_planning_key():
    client = OpenAIWorkflowClient(
        Settings(
            _env_file=None,
            openai_api_key="writing-key",
            openai_model="gpt-writing",
            planning_model="deepseek-v4-pro",
        ),
        profile="planning",
    )

    assert client.model == "gpt-writing"
