from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


WorkflowStep = Literal[
    "materials",
    "intake",
    "matrix",
    "breakthrough",
    "brief",
    "article",
    "archive",
]

ParseMode = Literal["smart", "text_only", "full_ocr"]
ParseSource = Literal["fresh", "cache", "skipped_existing"]

STEP_ORDER: list[WorkflowStep] = [
    "materials",
    "intake",
    "matrix",
    "breakthrough",
    "brief",
    "article",
    "archive",
]

RUNNABLE_STEPS: list[WorkflowStep] = [
    "intake",
    "matrix",
    "breakthrough",
    "brief",
    "article",
]


class StepState(BaseModel):
    status: Literal["pending", "running", "completed", "confirmed", "failed"] = "pending"
    input: dict[str, Any] = Field(default_factory=dict)
    output: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    confirmed_at: str | None = None
    updated_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class Material(BaseModel):
    id: str
    filename: str
    stored_name: str
    content_type: str | None = None
    size: int = 0
    sha256: str | None = None
    parsed_path: str | None = None
    status: Literal["uploaded", "parsed", "failed"] = "uploaded"
    error: str | None = None
    parse_mode: ParseMode | None = None
    parser_version: str | None = None
    parse_source: ParseSource | None = None
    parsed_chars: int = 0
    ocr_pages: int = 0
    parsed_at: str | None = None


class CustomSource(BaseModel):
    id: str
    source_id: str
    source_step: Literal["custom"] = "custom"
    keyword: str
    type: str
    title: str
    role: str = "用户自定义选题"
    brief_focus: str = ""
    channel: str = ""
    channels: list[str] = Field(default_factory=list)
    status: Literal["ready", "completed"] = "ready"
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    raw: dict[str, Any] = Field(default_factory=dict)


class Job(BaseModel):
    id: str
    step: WorkflowStep
    status: Literal["queued", "running", "cancelling", "cancelled", "completed", "failed"] = "queued"
    error: str | None = None
    total_count: int = 0
    completed_count: int = 0
    failed_count: int = 0
    skipped_count: int = 0
    current_item: str | None = None
    message: str | None = None
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class Project(BaseModel):
    id: str
    name: str
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    materials: list[Material] = Field(default_factory=list)
    custom_sources: list[CustomSource] = Field(default_factory=list)
    steps: dict[WorkflowStep, StepState] = Field(default_factory=dict)
    jobs: list[Job] = Field(default_factory=list)


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class ParseMaterialsRequest(BaseModel):
    mode: ParseMode = "smart"
    force: bool = False


class RunStepRequest(BaseModel):
    payload: dict[str, Any] = Field(default_factory=dict)


class ApplyMatrixImportRequest(BaseModel):
    overwrite: bool = False


class BreakthroughKeywordSelectionRequest(BaseModel):
    keywords: list[str] = Field(default_factory=list)


class CustomSourceRequest(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    keyword: str = Field(default="", max_length=120)
    type: str = Field(default="", max_length=80)
    brief_focus: str = Field(default="", max_length=1000)
    channel: str = Field(default="", max_length=120)
    channels: list[str] = Field(default_factory=list)
    raw: dict[str, Any] = Field(default_factory=dict)


class CustomSourceBatchRequest(BaseModel):
    titles: list[str] = Field(default_factory=list)
    type: str = Field(min_length=1, max_length=80)
    brief_focus: str = Field(default="", max_length=1000)
    channel: str = Field(default="", max_length=120)
    channels: list[str] = Field(default_factory=list)
    raw: dict[str, Any] = Field(default_factory=dict)


class ConfirmStepRequest(BaseModel):
    notes: str | None = None


class UpdateItemRequest(BaseModel):
    payload: dict[str, Any] = Field(default_factory=dict)


class HealthResponse(BaseModel):
    status: str
    model: str
    skill_available: bool
