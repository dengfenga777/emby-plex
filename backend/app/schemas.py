from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .enums import MediaType, RequestStatus, UserRole


class TelegramProfileIn(BaseModel):
    id: int
    username: str | None = None
    first_name: str | None = None
    last_name: str | None = None


class AuthSessionRequest(BaseModel):
    init_data: str | None = None
    profile: TelegramProfileIn | None = None


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tg_user_id: int
    username: str | None
    nickname: str
    role: UserRole
    created_at: datetime


class AuthSessionResponse(BaseModel):
    token: str
    auth_mode: str
    user: UserOut


class SearchResult(BaseModel):
    source_id: str
    source: str
    title: str
    media_type: MediaType
    year: int | None = None
    overview: str | None = None
    poster_url: str | None = None


class SearchResponse(BaseModel):
    items: list[SearchResult]


class RequestCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    media_type: MediaType
    source: str = Field(min_length=1, max_length=32)
    source_id: str = Field(min_length=1, max_length=128)
    overview: str | None = None
    poster_url: str | None = None
    year: int | None = None


class RequestLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    from_status: RequestStatus | None
    to_status: RequestStatus
    operator: str
    note: str | None
    created_at: datetime


class RequestSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    public_id: int
    title: str
    media_type: MediaType
    source: str
    source_id: str
    overview: str | None
    poster_url: str | None
    year: int | None
    status: RequestStatus
    moviepilot_task_id: str | None
    admin_note: str | None
    created_at: datetime
    updated_at: datetime


class RequestDetail(RequestSummary):
    user: UserOut
    logs: list[RequestLogOut]


class AdminRequestSummary(RequestSummary):
    user: UserOut


class AdminAction(BaseModel):
    note: str | None = None


class AdminResourceCandidate(BaseModel):
    title: str
    subtitle: str | None = None
    description: str | None = None
    site_name: str | None = None
    size: float | None = None
    seeders: int | None = None
    peers: int | None = None
    grabs: int | None = None
    pubdate: str | None = None
    page_url: str | None = None
    resource_type: str | None = None
    resource_pix: str | None = None
    resource_effect: str | None = None
    video_encode: str | None = None
    audio_encode: str | None = None
    season_episode: str | None = None
    volume_factor: str | None = None
    download_volume_factor: float | None = None
    upload_volume_factor: float | None = None
    hit_and_run: bool | None = None
    recommendation: str | None = None
    score: int = 0
    labels: list[str] = Field(default_factory=list)
    media_payload: dict[str, Any]
    torrent_payload: dict[str, Any]


class AdminDownloadAction(BaseModel):
    note: str | None = None
    media_payload: dict[str, Any]
    torrent_payload: dict[str, Any]


class StatusMessage(BaseModel):
    detail: str
