import json
from typing import Any

from openai import OpenAI

from app.core.config import Settings


class OpenAIWorkflowClient:
    def __init__(self, settings: Settings):
        if not settings.openai_api_key:
            raise RuntimeError("缺少 OPENAI_API_KEY，请在 .env 中配置后重试。")
        self.model = settings.openai_model
        kwargs: dict[str, str] = {"api_key": settings.openai_api_key}
        if settings.openai_base_url:
            kwargs["base_url"] = settings.openai_base_url.rstrip("/")
        self.client = OpenAI(**kwargs)

    def generate_json(self, *, system: str, user: str, schema_name: str) -> dict[str, Any]:
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
