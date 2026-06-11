import json
from typing import Any

from openai import OpenAI

from app.core.config import Settings


class OpenAIWorkflowClient:
    def __init__(self, settings: Settings):
        if not settings.openai_api_key:
            raise RuntimeError("缺少 OPENAI_API_KEY，请在 .env 中配置后重试。")
        self.model = settings.openai_model
        kwargs: dict[str, Any] = {"api_key": settings.openai_api_key, "timeout": settings.openai_timeout_seconds}
        if settings.openai_base_url:
            kwargs["base_url"] = settings.openai_base_url.rstrip("/")
        self.client = OpenAI(**kwargs)
        self.api_mode = settings.openai_api_mode.lower().strip()
        self.stream = bool(settings.openai_stream)

    def generate_json(self, *, system: str, user: str, schema_name: str) -> dict[str, Any]:
        if self.api_mode == "chat":
            return self._generate_json_with_chat(system=system, user=user, schema_name=schema_name)
        if self.api_mode != "responses":
            raise RuntimeError("OPENAI_API_MODE 只支持 chat 或 responses。")
        response = self.client.responses.create(
            model=self.model,
            input=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            text={
                "format": {
                    "type": "json_schema",
                    "name": schema_name,
                    "schema": json_object_schema(schema_name),
                    "strict": False,
                }
            },
        )
        text = extract_output_text(response)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {"title": schema_name, "markdown": text, "raw": text}

    def generate_markdown(self, *, system: str, user: str, schema_name: str) -> dict[str, Any]:
        return self.generate_json(system=system, user=user, schema_name=schema_name)

    def _generate_json_with_chat(self, *, system: str, user: str, schema_name: str) -> dict[str, Any]:
        messages = [
            {
                "role": "system",
                "content": (
                    system
                    + "\n\n你必须只输出一个 JSON 对象，不要输出 Markdown 代码围栏或解释文字。"
                ),
            },
            {"role": "user", "content": user},
        ]
        if self.stream:
            text = self._generate_chat_text_stream(messages=messages)
        else:
            text = self._generate_chat_text(messages=messages)
        return parse_json_or_raw(text, schema_name)

    def _generate_chat_text(self, *, messages: list[dict[str, str]]) -> str:
        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            response_format={"type": "json_object"},
        )
        return response.choices[0].message.content or "{}"

    def _generate_chat_text_stream(self, *, messages: list[dict[str, str]]) -> str:
        stream = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            response_format={"type": "json_object"},
            stream=True,
        )
        chunks: list[str] = []
        for event in stream:
            for choice in getattr(event, "choices", []) or []:
                delta = getattr(choice, "delta", None)
                content = getattr(delta, "content", None)
                if content:
                    chunks.append(str(content))
        return "".join(chunks) or "{}"


def extract_output_text(response: Any) -> str:
    output_text = getattr(response, "output_text", None)
    if output_text:
        return output_text
    chunks: list[str] = []
    for item in getattr(response, "output", []) or []:
        for content in getattr(item, "content", []) or []:
            text = getattr(content, "text", None)
            if text:
                chunks.append(text)
    return "\n".join(chunks).strip()


def parse_json_or_raw(text: str, schema_name: str) -> dict[str, Any]:
    try:
        return json.loads(strip_json_fence(text))
    except json.JSONDecodeError:
        return {"title": schema_name, "markdown": text, "raw": text}


def json_object_schema(name: str) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": True,
        "properties": {
            "title": {"type": "string"},
            "summary": {"type": "string"},
            "markdown": {"type": "string"},
            "items": {"type": "array", "items": {"type": "object", "additionalProperties": True}},
            "warnings": {"type": "array", "items": {"type": "string"}},
        },
        "required": [],
    }


def strip_json_fence(text: str) -> str:
    value = text.strip()
    if value.startswith("```"):
        value = value.removeprefix("```json").removeprefix("```").strip()
        value = value.removesuffix("```").strip()
    return value
