from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload

from ..config import Settings
from ..database import get_db
from ..deps import get_app_settings, get_current_user
from ..enums import RequestStatus
from ..models import Request, User
from ..schemas import RequestCreate, RequestDetail, RequestSummary
from ..services.request_identity import build_request_lookup_filter
from ..services.moviepilot import MoviePilotError, MoviePilotService
from ..services.request_workflow import (
    add_request_log,
    build_submission_failure_message,
    can_view_request,
    submit_request_to_moviepilot,
    sync_request_status,
    transition_request_status,
)

router = APIRouter(tags=["requests"])


@router.post("/requests", response_model=RequestDetail, status_code=status.HTTP_201_CREATED)
async def create_request(
    payload: RequestCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    settings: Settings = Depends(get_app_settings),
) -> RequestDetail:
    moviepilot_service = MoviePilotService(settings)
    initial_status = RequestStatus.pending if settings.require_admin_approval else RequestStatus.approved

    request = Request(
        user_id=current_user.id,
        title=payload.title,
        media_type=payload.media_type,
        source=payload.source,
        source_id=payload.source_id,
        overview=payload.overview,
        poster_url=payload.poster_url,
        year=payload.year,
        status=initial_status,
    )
    db.add(request)
    db.flush()
    add_request_log(
        db,
        request,
        from_status=None,
        to_status=initial_status,
        operator=f"user:{current_user.tg_user_id}",
        note="Request created.",
    )

    if not settings.require_admin_approval:
        try:
            await submit_request_to_moviepilot(
                db,
                request,
                moviepilot_service,
                operator="system:auto-submit",
            )
        except MoviePilotError as exc:
            transition_request_status(
                db,
                request,
                RequestStatus.failed,
                operator="system:auto-submit",
                note=build_submission_failure_message(exc),
            )

    db.commit()
    db.refresh(request)

    hydrated = (
        db.query(Request)
        .options(joinedload(Request.user), joinedload(Request.logs))
        .filter(build_request_lookup_filter(request.id))
        .first()
    )
    return RequestDetail.model_validate(hydrated)


@router.get("/my/requests", response_model=list[RequestSummary])
async def list_my_requests(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    settings: Settings = Depends(get_app_settings),
) -> list[RequestSummary]:
    moviepilot_service = MoviePilotService(settings)
    items = (
        db.query(Request)
        .filter(Request.user_id == current_user.id)
        .order_by(Request.created_at.desc())
        .all()
    )

    for item in items:
        await sync_request_status(db, item, moviepilot_service)

    return [RequestSummary.model_validate(item) for item in items]


@router.get("/requests/{request_id}", response_model=RequestDetail)
async def get_request_detail(
    request_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    settings: Settings = Depends(get_app_settings),
) -> RequestDetail:
    request = (
        db.query(Request)
        .options(joinedload(Request.user), joinedload(Request.logs))
        .filter(build_request_lookup_filter(request_id))
        .first()
    )
    if request is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Request not found.")
    if not can_view_request(request, current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No access to this request.")

    moviepilot_service = MoviePilotService(settings)
    await sync_request_status(db, request, moviepilot_service)
    db.refresh(request)
    return RequestDetail.model_validate(request)
