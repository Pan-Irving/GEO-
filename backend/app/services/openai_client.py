import json
from typing import Any

from openai import OpenAI

from app.core.config import Settings


class OpenAIWorkflowClient:
    def __init__(self, settings: Settings, profile: str = "default"):
        config = workflow_client_config(settings, profile)
        if not config["api_key"]:
            env_name = "PLANNING_API_KEY" if profile == "planning" else "OPENAI_API_KEY"
            raise RuntimeError(f"缺少 {env_name}，请在 .env 中配置后重试。")
        self.profile = profile
        self.model = str(config["model"])
        kwargs: dict[str, Any] = {"api_key": config["api_key"], "timeout": config["timeout"]}
        if config["base_url"]:
            kwargs["base_url"] = str(config["base_url"]).rstrip("/")
        self.client = OpenAI(**kwargs)
        self.api_mode = str(config["api_mode"]).lower().strip()
        self.stream = bool(config["stream"])

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

    def generate_text(self, *, system: str, user: str) -> str:
        if self.api_mode == "chat":
            messages = [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ]
            if self.stream:
                return self._generate_chat_text_stream(messages=messages, response_format=None)
            return self._generate_chat_text(messages=messages, response_format=None)
        if self.api_mode != "responses":
            raise RuntimeError("OPENAI_API_MODE 只支持 chat 或 responses。")
        response = self.client.responses.create(
            model=self.model,
            input=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return extract_output_text(response).strip()

    def generate_markdown(self, *, system: str, user: str, schema_name: str) -> dict[str, Any]:
        return {"title": schema_name, "markdown": self.generate_text(system=system, user=user)}

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
        response_format = {"type": "json_object"}
        if self.stream:
            text = self._generate_chat_text_stream(messages=messages, response_format=response_format)
        else:
            text = self._generate_chat_text(messages=messages, response_format=response_format)
        return parse_json_or_raw(text, schema_name)

    def _generate_chat_text(self, *, messages: list[dict[str, str]], response_format: dict[str, Any] | None) -> str:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
        }
        if response_format is not None:
            kwargs["response_format"] = response_format
        response = self.client.chat.completions.create(**kwargs)
        return response.choices[0].message.content or "{}"

    def _generate_chat_text_stream(self, *, messages: list[dict[str, str]], response_format: dict[str, Any] | None) -> str:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": True,
        }
        if response_format is not None:
            kwargs["response_format"] = response_format
        stream = self.client.chat.completions.create(**kwargs)
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


def workflow_client_config(settings: Settings, profile: str = "default") -> dict[str, Any]:
    if profile == "planning" and settings.planning_api_key:
        return {
            "api_key": settings.planning_api_key,
            "base_url": settings.planning_base_url or settings.openai_base_url,
            "model": settings.planning_model or settings.openai_model,
            "api_mode": settings.planning_api_mode or settings.openai_api_mode,
            "stream": settings.openai_stream if settings.planning_stream is None else settings.planning_stream,
            "timeout": settings.planning_timeout_seconds or settings.openai_timeout_seconds,
        }
    return {
        "api_key": settings.openai_api_key,
        "base_url": settings.openai_base_url,
        "model": settings.openai_model,
        "api_mode": settings.openai_api_mode,
        "stream": settings.openai_stream,
        "timeout": settings.openai_timeout_seconds,
    }
