from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from ..enums import RequestStatus
from ..models import Request, RequestLog, User
from .moviepilot import MoviePilotError, MoviePilotService

SYNCABLE_STATUSES = {
    RequestStatus.submitted_to_moviepilot,
    RequestStatus.downloading,
    RequestStatus.organizing,
}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def add_request_log(
    db: Session,
    request: Request,
    from_status: RequestStatus | None,
    to_status: RequestStatus,
    operator: str,
    note: str | None = None,
) -> None:
    log = RequestLog(
        request_id=request.id,
        from_status=from_status,
        to_status=to_status,
        operator=operator,
        note=note,
    )
    db.add(log)


def transition_request_status(
    db: Session,
    request: Request,
    to_status: RequestStatus,
    operator: str,
    note: str | None = None,
) -> None:
    from_status = request.status
    request.status = to_status
    request.updated_at = utcnow()
    if note:
        request.admin_note = note
    if to_status == RequestStatus.submitted_to_moviepilot and request.submitted_at is None:
        request.submitted_at = utcnow()
    if to_status == RequestStatus.finished:
        request.finished_at = utcnow()
    add_request_log(db, request, from_status, to_status, operator, note)


async def submit_request_to_moviepilot(
    db: Session,
    request: Request,
    moviepilot_service: MoviePilotService,
    operator: str,
) -> None:
    submission = await moviepilot_service.create_task(request)
    request.moviepilot_task_id = submission.task_id
    transition_request_status(
        db,
        request,
        submission.status,
        operator=operator,
        note=submission.note or "Request forwarded to MoviePilot.",
    )


async def sync_request_status(
    db: Session,
    request: Request,
    moviepilot_service: MoviePilotService,
) -> Request:
    if request.status not in SYNCABLE_STATUSES:
        return request

    next_status = await moviepilot_service.get_task_status(request)
    if next_status != request.status:
        transition_request_status(
            db,
            request,
            next_status,
            operator="moviepilot-sync",
            note="Status synchronized from MoviePilot.",
        )
        db.commit()
        db.refresh(request)

    return request


def can_view_request(request: Request, user: User) -> bool:
    return request.user_id == user.id or user.role.value == "admin"


def build_submission_failure_message(exc: MoviePilotError) -> str:
    return f"MoviePilot submission failed: {exc}"
