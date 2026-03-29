from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session, joinedload

from ..config import Settings
from ..database import get_db
from ..deps import get_admin_user, get_app_settings
from ..enums import RequestStatus
from ..models import Request, User
from ..schemas import (
    AdminAction,
    AdminBatchAction,
    AdminBatchActionResult,
    AdminBatchSkippedItem,
    AdminDownloadAction,
    AdminRequestSummary,
    AdminResourceCandidate,
    RequestDetail,
)
from ..services.notifications import (
    build_batch_summary_text,
    build_request_status_notification_text,
    send_telegram_message,
)
from ..services.request_identity import build_request_lookup_filter
from ..services.moviepilot import MoviePilotError, MoviePilotService
from ..services.request_workflow import (
    build_submission_failure_message,
    submit_request_to_moviepilot,
    sync_request_status,
    transition_request_status,
)

router = APIRouter(prefix="/admin", tags=["admin"])


def get_request_or_404(db: Session, request_id: str) -> Request:
    request = (
        db.query(Request)
        .options(joinedload(Request.user), joinedload(Request.logs))
        .filter(build_request_lookup_filter(request_id))
        .first()
    )
    if request is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Request not found.")
    return request


def get_request_or_none(db: Session, request_id: str) -> Request | None:
    return (
        db.query(Request)
        .options(joinedload(Request.user), joinedload(Request.logs))
        .filter(build_request_lookup_filter(request_id))
        .first()
    )


def ensure_admin_actionable(request: Request) -> None:
    if request.status not in {RequestStatus.pending, RequestStatus.failed, RequestStatus.approved}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Request cannot be handled from {request.status.value}.",
        )


def transition_to_approved_if_needed(
    db: Session,
    request: Request,
    admin_user: User,
    note: str | None,
) -> None:
    if request.status == RequestStatus.approved:
        return

    transition_request_status(
        db,
        request,
        RequestStatus.approved,
        operator=f"admin:{admin_user.tg_user_id}",
        note=note or "Approved by admin.",
    )


def serialize_request_detail(request: Request) -> RequestDetail:
    return RequestDetail.model_validate(request)


async def execute_subscribe_action(
    db: Session,
    request: Request,
    *,
    admin_user: User,
    settings: Settings,
    note: str | None,
) -> Request:
    ensure_admin_actionable(request)

    moviepilot_service = MoviePilotService(settings)
    transition_to_approved_if_needed(db, request, admin_user, note)

    try:
        await submit_request_to_moviepilot(
            db,
            request,
            moviepilot_service,
            operator=f"admin:{admin_user.tg_user_id}",
        )
    except MoviePilotError as exc:
        transition_request_status(
            db,
            request,
            RequestStatus.failed,
            operator=f"admin:{admin_user.tg_user_id}",
            note=build_submission_failure_message(exc),
        )

    return request


def execute_reject_action(
    db: Session,
    request: Request,
    *,
    admin_user: User,
    note: str | None,
) -> Request:
    if request.status in {RequestStatus.rejected, RequestStatus.finished}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Request cannot be rejected from {request.status.value}.",
        )

    transition_request_status(
        db,
        request,
        RequestStatus.rejected,
        operator=f"admin:{admin_user.tg_user_id}",
        note=note or "Rejected by admin.",
    )
    return request


def dedupe_request_ids(request_ids: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for request_id in request_ids:
        if request_id in seen:
            continue
        seen.add(request_id)
        deduped.append(request_id)
    return deduped


def build_batch_response(
    items: list[Request],
    skipped: list[AdminBatchSkippedItem],
) -> AdminBatchActionResult:
    return AdminBatchActionResult(
        processed_count=len(items),
        skipped_count=len(skipped),
        processed_ids=[item.id for item in items],
        skipped=skipped,
        items=[serialize_request_detail(item) for item in items],
    )


async def notify_request_status_change(settings: Settings, request: Request) -> None:
    if request.user is None:
        return
    await send_telegram_message(
        settings,
        chat_id=request.user.tg_user_id,
        text=build_request_status_notification_text(request),
    )


@router.get("/requests", response_model=list[AdminRequestSummary])
async def list_admin_requests(
    status_filter: RequestStatus | None = Query(default=None, alias="status"),
    db: Session = Depends(get_db),
    _: User = Depends(get_admin_user),
    settings: Settings = Depends(get_app_settings),
) -> list[AdminRequestSummary]:
    moviepilot_service = MoviePilotService(settings)
    query = db.query(Request).options(joinedload(Request.user)).order_by(Request.created_at.desc())
    if status_filter is not None:
        query = query.filter(Request.status == status_filter)
    items = query.all()
    for item in items:
        await sync_request_status(db, item, moviepilot_service)
    return [AdminRequestSummary.model_validate(item) for item in items]


@router.get("/requests/{request_id}/resources", response_model=list[AdminResourceCandidate])
async def search_request_resources(
    request_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(get_admin_user),
    settings: Settings = Depends(get_app_settings),
) -> list[AdminResourceCandidate]:
    request = get_request_or_404(db, request_id)
    ensure_admin_actionable(request)

    moviepilot_service = MoviePilotService(settings)
    items = await moviepilot_service.search_resources(request)
    return [AdminResourceCandidate.model_validate(item.__dict__) for item in items]


@router.post("/requests/{request_id}/approve", response_model=RequestDetail)
async def approve_request(
    request_id: str,
    payload: AdminAction,
    db: Session = Depends(get_db),
    admin_user: User = Depends(get_admin_user),
    settings: Settings = Depends(get_app_settings),
) -> RequestDetail:
    return await subscribe_request(request_id, payload, db, admin_user, settings)


@router.post("/requests/{request_id}/subscribe", response_model=RequestDetail)
async def subscribe_request(
    request_id: str,
    payload: AdminAction,
    db: Session = Depends(get_db),
    admin_user: User = Depends(get_admin_user),
    settings: Settings = Depends(get_app_settings),
) -> RequestDetail:
    request = get_request_or_404(db, request_id)
    await execute_subscribe_action(
        db,
        request,
        admin_user=admin_user,
        settings=settings,
        note=payload.note,
    )

    db.commit()
    db.refresh(request)
    await notify_request_status_change(settings, request)
    return serialize_request_detail(request)


@router.post("/requests/{request_id}/download", response_model=RequestDetail)
async def direct_download_request(
    request_id: str,
    payload: AdminDownloadAction,
    db: Session = Depends(get_db),
    admin_user: User = Depends(get_admin_user),
    settings: Settings = Depends(get_app_settings),
) -> RequestDetail:
    request = get_request_or_404(db, request_id)
    ensure_admin_actionable(request)

    moviepilot_service = MoviePilotService(settings)
    transition_to_approved_if_needed(
        db,
        request,
        admin_user,
        payload.note or "Approved by admin for direct download.",
    )

    try:
        submission = await moviepilot_service.download_resource(
            request,
            media_payload=payload.media_payload,
            torrent_payload=payload.torrent_payload,
        )
        request.moviepilot_task_id = submission.task_id
        transition_request_status(
            db,
            request,
            submission.status,
            operator=f"admin:{admin_user.tg_user_id}",
            note=submission.note or "Direct download task created.",
        )
    except MoviePilotError as exc:
        transition_request_status(
            db,
            request,
            RequestStatus.failed,
            operator=f"admin:{admin_user.tg_user_id}",
            note=build_submission_failure_message(exc),
        )

    db.commit()
    db.refresh(request)
    await notify_request_status_change(settings, request)
    return serialize_request_detail(request)


@router.post("/requests/{request_id}/reject", response_model=RequestDetail)
async def reject_request(
    request_id: str,
    payload: AdminAction,
    db: Session = Depends(get_db),
    admin_user: User = Depends(get_admin_user),
    settings: Settings = Depends(get_app_settings),
) -> RequestDetail:
    request = get_request_or_404(db, request_id)
    execute_reject_action(
        db,
        request,
        admin_user=admin_user,
        note=payload.note,
    )
    db.commit()
    db.refresh(request)
    await notify_request_status_change(settings, request)
    return serialize_request_detail(request)


@router.post("/batch/requests/subscribe", response_model=AdminBatchActionResult)
async def batch_subscribe_requests(
    payload: AdminBatchAction,
    db: Session = Depends(get_db),
    admin_user: User = Depends(get_admin_user),
    settings: Settings = Depends(get_app_settings),
) -> AdminBatchActionResult:
    items: list[Request] = []
    skipped: list[AdminBatchSkippedItem] = []

    for request_id in dedupe_request_ids(payload.request_ids):
        request = get_request_or_none(db, request_id)
        if request is None:
            skipped.append(AdminBatchSkippedItem(request_id=request_id, detail="Request not found."))
            continue

        try:
            await execute_subscribe_action(
                db,
                request,
                admin_user=admin_user,
                settings=settings,
                note=payload.note,
            )
            items.append(request)
        except HTTPException as exc:
            skipped.append(AdminBatchSkippedItem(request_id=request_id, detail=str(exc.detail)))

    db.commit()
    for item in items:
        db.refresh(item)
        await notify_request_status_change(settings, item)
    await send_telegram_message(
        settings,
        chat_id=admin_user.tg_user_id,
        text=build_batch_summary_text(
            action_label="批量通过",
            processed_count=len(items),
            skipped_count=len(skipped),
            processed_ids=[str(item.public_id or item.id) for item in items],
        ),
    )
    return build_batch_response(items, skipped)


@router.post("/batch/requests/reject", response_model=AdminBatchActionResult)
async def batch_reject_requests(
    payload: AdminBatchAction,
    db: Session = Depends(get_db),
    admin_user: User = Depends(get_admin_user),
    settings: Settings = Depends(get_app_settings),
) -> AdminBatchActionResult:
    items: list[Request] = []
    skipped: list[AdminBatchSkippedItem] = []

    for request_id in dedupe_request_ids(payload.request_ids):
        request = get_request_or_none(db, request_id)
        if request is None:
            skipped.append(AdminBatchSkippedItem(request_id=request_id, detail="Request not found."))
            continue

        try:
            execute_reject_action(
                db,
                request,
                admin_user=admin_user,
                note=payload.note,
            )
            items.append(request)
        except HTTPException as exc:
            skipped.append(AdminBatchSkippedItem(request_id=request_id, detail=str(exc.detail)))

    db.commit()
    for item in items:
        db.refresh(item)
        await notify_request_status_change(settings, item)
    await send_telegram_message(
        settings,
        chat_id=admin_user.tg_user_id,
        text=build_batch_summary_text(
            action_label="批量拒绝",
            processed_count=len(items),
            skipped_count=len(skipped),
            processed_ids=[str(item.public_id or item.id) for item in items],
        ),
    )
    return build_batch_response(items, skipped)
