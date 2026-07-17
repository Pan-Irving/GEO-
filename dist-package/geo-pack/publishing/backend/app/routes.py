from typing import Any

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from app.config import Settings, get_settings
from app.db import AI_PLATFORMS, SELF_MEDIA, WEB_CATEGORIES, PublishingStore
from app.sync_service import SyncError, sync_writing_project


router = APIRouter(prefix="/api")


class LoginRequest(BaseModel):
    username: str
    password: str


class UserCreateRequest(BaseModel):
    username: str
    password: str = Field(min_length=6)
    display_name: str = ""
    role: str = "employee"


class UserUpdateRequest(BaseModel):
    display_name: str | None = None
    role: str | None = None
    active: bool | None = None
    password: str | None = None


class AssignmentRequest(BaseModel):
    user_id: str
    project_id: str
    intent_group_ids: list[str] = Field(default_factory=list)
    intent_groups: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    article_types: list[str] = Field(default_factory=list)


class SelfPublicationRequest(BaseModel):
    article_id: str
    media_name: str
    target_ai_platforms: list[str]
    publish_url: str
    published_at: str = ""
    note: str = ""


class WebPublicationRequest(BaseModel):
    article_id: str
    media_category: str
    media_name: str = ""
    media_requirement: str = ""
    publisher: str = ""
    target_ai_platforms: list[str]
    reference_url: str = ""
    published_at: str = ""
    note: str = ""


class PublicationUpdateRequest(BaseModel):
    media_name: str | None = None
    publish_url: str | None = None
    order_id: str | None = None
    actual_cost: float | None = None
    order_status: str | None = None
    published_at: str | None = None
    target_ai_platforms: list[str] | None = None
    note: str | None = None


def store(settings: Settings = Depends(get_settings)) -> PublishingStore:
    return PublishingStore(settings)


def token_from_header(authorization: str = Header(default="")) -> str:
    if authorization.lower().startswith("bearer "):
        return authorization.split(" ", 1)[1].strip()
    return ""


def current_user(token: str = Depends(token_from_header), db: PublishingStore = Depends(store)) -> dict[str, Any]:
    user = db.user_for_token(token)
    if not user:
        raise HTTPException(status_code=401, detail="请先登录。")
    return user


def admin_user(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    if user["role"] not in {"admin", "manager"}:
        raise HTTPException(status_code=403, detail="需要管理员权限。")
    return user


@router.get("/health")
def health(settings: Settings = Depends(get_settings)):
    return {
        "status": "ok",
        "database": settings.publishing_database_url or str(settings.database_path),
        "writing_api_base_url": settings.writing_api_base_url,
    }


@router.post("/auth/login")
def login(payload: LoginRequest, db: PublishingStore = Depends(store)):
    result = db.login(payload.username, payload.password)
    if not result:
        raise HTTPException(status_code=401, detail="账号或密码错误。")
    return result


@router.get("/auth/me")
def me(user: dict[str, Any] = Depends(current_user)):
    return {"user": user}


@router.post("/auth/logout")
def logout(token: str = Depends(token_from_header), db: PublishingStore = Depends(store)):
    db.logout(token)
    return {"ok": True}


@router.get("/meta/options")
def options():
    return {"ai_platforms": AI_PLATFORMS, "self_media": SELF_MEDIA, "web_categories": WEB_CATEGORIES}


@router.get("/writing/projects")
def writing_projects(
    _: dict[str, Any] = Depends(admin_user),
    db: PublishingStore = Depends(store),
    settings: Settings = Depends(get_settings),
):
    base_url = settings.writing_api_base_url.rstrip("/")
    try:
        response = httpx.get(f"{base_url}/api/projects", timeout=15)
        response.raise_for_status()
    except httpx.RequestError as exc:
        raise HTTPException(status_code=502, detail="无法连接撰文系统，请确认 8000 后端已启动。") from exc
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=502, detail="读取撰文项目失败，请确认撰文系统接口正常。") from exc
    body = response.json()
    if not isinstance(body, list):
        raise HTTPException(status_code=502, detail="撰文系统返回格式异常。")
    synced_ids = db.synced_project_ids()
    projects: list[dict[str, Any]] = []
    for item in body:
        if not isinstance(item, dict):
            continue
        project_id = str(item.get("id") or "").strip()
        if not project_id:
            continue
        projects.append(
            {
                "id": project_id,
                "name": str(item.get("name") or project_id).strip(),
                "updated_at": str(item.get("updated_at") or "").strip(),
                "synced": project_id in synced_ids,
            }
        )
    return {"projects": projects}


@router.get("/admin/users")
def list_users(_: dict[str, Any] = Depends(admin_user), db: PublishingStore = Depends(store)):
    return {"users": db.list_users()}


@router.post("/admin/users")
def create_user(payload: UserCreateRequest, _: dict[str, Any] = Depends(admin_user), db: PublishingStore = Depends(store)):
    try:
        return {"user": db.create_user(payload.model_dump())}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/admin/users/{user_id}")
def update_user(user_id: str, payload: UserUpdateRequest, user: dict[str, Any] = Depends(admin_user), db: PublishingStore = Depends(store)):
    try:
        return {"user": db.update_user(user_id, payload.model_dump(exclude_unset=True), actor=user)}
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/admin/assignments")
def list_assignments(_: dict[str, Any] = Depends(admin_user), db: PublishingStore = Depends(store)):
    return {"assignments": db.list_assignments()}


@router.post("/admin/assignments")
def create_assignment(payload: AssignmentRequest, _: dict[str, Any] = Depends(admin_user), db: PublishingStore = Depends(store)):
    try:
        return {"assignment": db.create_assignment(payload.model_dump())}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/admin/assignments/{assignment_id}")
def delete_assignment(assignment_id: str, _: dict[str, Any] = Depends(admin_user), db: PublishingStore = Depends(store)):
    db.delete_assignment(assignment_id)
    return {"deleted": True}


@router.post("/sync/projects/{writing_project_id}")
def sync_project(
    writing_project_id: str,
    _: dict[str, Any] = Depends(admin_user),
    db: PublishingStore = Depends(store),
    settings: Settings = Depends(get_settings),
):
    try:
        return sync_writing_project(db, settings, writing_project_id)
    except SyncError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.get("/projects")
def list_projects(user: dict[str, Any] = Depends(current_user), db: PublishingStore = Depends(store)):
    return {"projects": db.visible_projects(user)}


@router.get("/projects/{project_id}/inventory")
def inventory(project_id: str, user: dict[str, Any] = Depends(current_user), db: PublishingStore = Depends(store)):
    return db.inventory(project_id, user)


@router.get("/projects/{project_id}/records")
def project_records(project_id: str, user: dict[str, Any] = Depends(current_user), db: PublishingStore = Depends(store)):
    return {"records": db.records_for_project(project_id, user)}


@router.get("/projects/{project_id}/usage-summary")
def usage_summary(
    project_id: str,
    token: str = Depends(token_from_header),
    db: PublishingStore = Depends(store),
):
    if not token:
        return db.usage_summary(project_id)
    user = db.user_for_token(token)
    if not user:
        raise HTTPException(status_code=401, detail="请先登录。")
    return db.usage_summary(project_id, user)


@router.get("/articles/{article_id}")
def article_detail(article_id: str, user: dict[str, Any] = Depends(current_user), db: PublishingStore = Depends(store)):
    try:
        return {"article": db.get_article(article_id, user)}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.post("/publications/self")
def create_self_publication(payload: SelfPublicationRequest, user: dict[str, Any] = Depends(current_user), db: PublishingStore = Depends(store)):
    try:
        return {"record": db.create_self_publication(user, payload.model_dump())}
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.post("/publications/web")
def create_web_publication(payload: WebPublicationRequest, user: dict[str, Any] = Depends(current_user), db: PublishingStore = Depends(store)):
    try:
        return {"record": db.create_web_publication(user, payload.model_dump())}
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.patch("/publications/{record_id}")
def update_publication(
    record_id: str,
    payload: PublicationUpdateRequest,
    user: dict[str, Any] = Depends(current_user),
    db: PublishingStore = Depends(store),
):
    try:
        return {"record": db.update_publication_for_user(record_id, user, payload.model_dump(exclude_unset=True))}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/publications/{record_id}")
def delete_publication(
    record_id: str,
    user: dict[str, Any] = Depends(current_user),
    db: PublishingStore = Depends(store),
):
    try:
        db.delete_publication_for_user(record_id, user)
        return {"deleted": True}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
