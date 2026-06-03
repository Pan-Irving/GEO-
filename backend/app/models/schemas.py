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
    "rewrite",
    "archive",
]

STEP_ORDER: list[WorkflowStep] = [
    "materials",
    "intake",
    "matrix",
    "breakthrough",
    "brief",
    "article",
    "rewrite",
    "archive",
]

RUNNABLE_STEPS: list[WorkflowStep] = [
    "intake",
    "matrix",
    "breakthrough",
    "brief",
    "article",
    "rewrite",
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
    parsed_path: str | None = None
    status: Literal["uploaded", "parsed", "failed"] = "uploaded"
    error: str | None = None


class Job(BaseModel):
    id: str
    step: WorkflowStep
    status: Literal["queued", "running", "completed", "failed"] = "queued"
    error: str | None = None
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class Project(BaseModel):
    id: str
    name: str
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    materials: list[Material] = Field(default_factory=list)
    steps: dict[WorkflowStep, StepState] = Field(default_factory=dict)
    jobs: list[Job] = Field(default_factory=list)


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class RunStepRequest(BaseModel):
    payload: dict[str, Any] = Field(default_factory=dict)


class ConfirmStepRequest(BaseModel):
    notes: str | None = None


class HealthResponse(BaseModel):
    status: str
    model: str
    skill_available: bool
