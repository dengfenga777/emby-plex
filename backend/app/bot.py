from __future__ import annotations

import asyncio
import logging
import re
from contextlib import suppress
from datetime import datetime, timedelta, timezone

from sqlalchemy import func
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, WebAppInfo
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters
from sqlalchemy.orm import joinedload

from . import database
from .config import get_settings
from .enums import MediaType, RequestStatus, UserRole
from .models import Request, User
from .schemas import TelegramProfileIn
from .services.auth import upsert_user
from .services.notifications import (
    STATUS_LABELS,
    build_finished_notification_text,
    build_request_status_notification_text,
    format_media_label,
    send_telegram_message,
)
from .services.request_identity import build_request_lookup_filter, format_request_reference
from .services.moviepilot import MoviePilotError, MoviePilotService
from .services.request_workflow import (
    SYNCABLE_STATUSES,
    add_request_log,
    build_submission_failure_message,
    find_existing_active_request,
    submit_request_to_moviepilot,
    sync_request_status,
    transition_request_status,
)
from .services.tmdb_links import extract_tmdb_links

logger = logging.getLogger(__name__)
REQUEST_REF_PATTERN = re.compile(r"请求 ID[:：]\s*([A-Za-z0-9_-]+)")


def build_webapp_keyboard() -> InlineKeyboardMarkup:
    settings = get_settings()
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("打开 MiniApp", web_app=WebAppInfo(url=settings.telegram_webapp_url))]]
    )


def ensure_database() -> None:
    settings = get_settings()
    if database.SessionLocal is None:
        database.configure_database(settings.database_url)
        database.init_database()


def build_request_from_item(
    user_id: int,
    item_title: str,
    item_media_type: str,
    item_source: str,
    item_source_id: str,
    item_overview: str | None,
    item_poster_url: str | None,
    item_year: int | None,
    status: RequestStatus,
) -> Request:
    return Request(
        user_id=user_id,
        title=item_title,
        media_type=MediaType(item_media_type),
        source=item_source,
        source_id=item_source_id,
        overview=item_overview,
        poster_url=item_poster_url,
        year=item_year,
        status=status,
    )


def build_bot_operator(user: User) -> str:
    return f"bot-admin:{user.tg_user_id}"


def build_profile_from_telegram_user(telegram_user) -> TelegramProfileIn:  # noqa: ANN001
    return TelegramProfileIn(
        id=telegram_user.id,
        username=telegram_user.username,
        first_name=telegram_user.first_name,
        last_name=telegram_user.last_name,
    )


def parse_request_command_args(args: list[str]) -> tuple[str | None, str | None]:
    if not args:
        return None, None
    request_ref = args[0].strip()
    note = " ".join(args[1:]).strip() or None
    return request_ref or None, note


def extract_request_ref_from_text(text: str) -> str | None:
    matches = REQUEST_REF_PATTERN.findall(text)
    if len(matches) != 1:
        return None
    return matches[0]


def resolve_request_ref_from_message(message) -> str | None:  # noqa: ANN001
    reply_to_message = getattr(message, "reply_to_message", None)
    if reply_to_message is None:
        return None
    reply_text = (reply_to_message.text or reply_to_message.caption or "").strip()
    if not reply_text:
        return None
    return extract_request_ref_from_text(reply_text)


def resolve_request_command_args(message, args: list[str]) -> tuple[str | None, str | None]:  # noqa: ANN001
    if args and args[0].strip().isdigit():
        request_ref = args[0].strip()
        note = " ".join(args[1:]).strip() or None
        return request_ref, note

    reply_request_ref = resolve_request_ref_from_message(message)
    if reply_request_ref is not None:
        note = " ".join(args).strip() or None
        return reply_request_ref, note

    return parse_request_command_args(args)


def parse_pending_limit(args: list[str], default: int = 10) -> int | None:
    if not args:
        return default
    raw = args[0].strip()
    if not raw.isdigit():
        return None
    return max(1, min(int(raw), 30))


PENDING_STATUS_ALIASES: dict[str, RequestStatus | None] = {
    "all": None,
    "全部": None,
    "pending": RequestStatus.pending,
    "待处理": RequestStatus.pending,
    "approved": RequestStatus.approved,
    "已批准": RequestStatus.approved,
    "rejected": RequestStatus.rejected,
    "已拒绝": RequestStatus.rejected,
    "submitted_to_moviepilot": RequestStatus.submitted_to_moviepilot,
    "submitted": RequestStatus.submitted_to_moviepilot,
    "已提交": RequestStatus.submitted_to_moviepilot,
    "已提交到moviepilot": RequestStatus.submitted_to_moviepilot,
    "downloading": RequestStatus.downloading,
    "下载中": RequestStatus.downloading,
    "organizing": RequestStatus.organizing,
    "整理中": RequestStatus.organizing,
    "finished": RequestStatus.finished,
    "已完成": RequestStatus.finished,
    "failed": RequestStatus.failed,
    "处理失败": RequestStatus.failed,
}


def parse_pending_status(token: str) -> tuple[bool, RequestStatus | None]:
    normalized = token.strip().lower()
    if normalized in PENDING_STATUS_ALIASES:
        return True, PENDING_STATUS_ALIASES[normalized]
    return False, None


def parse_pending_filters(
    args: list[str],
    default_limit: int = 10,
) -> tuple[int | None, RequestStatus | None, str | None]:
    if not args:
        return default_limit, RequestStatus.pending, None

    limit = default_limit
    rest = args[:]
    if rest and rest[0].strip().isdigit():
        limit = parse_pending_limit([rest[0]], default=default_limit)
        rest = rest[1:]
    elif rest and rest[0].strip().startswith("-"):
        return None, None, None

    if limit is None:
        return None, None, None

    status = RequestStatus.pending
    keyword_parts = rest
    if rest:
        matched_status, parsed_status = parse_pending_status(rest[0])
        if matched_status:
            status = parsed_status
            keyword_parts = rest[1:]

    keyword = " ".join(part.strip() for part in keyword_parts if part.strip()) or None
    return limit, status, keyword


def build_pending_response_header(
    *,
    status: RequestStatus | None,
    keyword: str | None,
    limit: int,
) -> str:
    if status == RequestStatus.pending and not keyword:
        return "待审批请求："

    status_label = "全部" if status is None else STATUS_LABELS.get(status, status.value)
    lines = [f"请求列表（状态：{status_label}，最多 {limit} 条）"]
    if keyword:
        lines.append(f"关键词：{keyword}")
    return "\n".join(lines) + "\n"


async def notify_request_user(settings, request: Request) -> None:  # noqa: ANN001
    if request.user is None:
        return
    await send_telegram_message(
        settings,
        chat_id=request.user.tg_user_id,
        text=build_request_status_notification_text(request),
    )


async def notify_request_chat(settings, request: Request) -> None:  # noqa: ANN001
    if request.notification_chat_id is None:
        return
    await send_telegram_message(
        settings,
        chat_id=request.notification_chat_id,
        text=build_request_status_notification_text(request),
        message_thread_id=request.notification_message_thread_id,
        reply_to_message_id=request.notification_message_id,
    )


def format_pending_request_line(request: Request) -> str:
    requester = request.user.nickname if request.user else "未知用户"
    year_suffix = f" ({request.year})" if request.year else ""
    return f"#{format_request_reference(request)} {request.title}{year_suffix} · {request.media_type.value} · 发起人 {requester}"


def build_request_action_hint(request: Request) -> str:
    request_ref = format_request_reference(request)
    actions = [f"/detail {request_ref}"]
    if request.status in {RequestStatus.pending, RequestStatus.failed, RequestStatus.approved}:
        actions.append(f"/approve {request_ref}")
    if request.status not in {RequestStatus.rejected, RequestStatus.finished}:
        actions.append(f"/reject {request_ref}")
    return "操作：" + " | ".join(actions)


def build_request_detail_text(request: Request) -> str:
    requester = request.user.nickname if request.user else "未知用户"
    status_label = STATUS_LABELS.get(request.status, request.status.value)
    lines = [
        f"{format_media_label(request.title, request.media_type, request.year)}",
        f"请求 ID：{format_request_reference(request)}",
        f"当前状态：{status_label}",
        f"发起人：{requester}",
        f"来源：{request.source} / {request.source_id}",
    ]
    if request.moviepilot_task_id:
        lines.append(f"任务：{request.moviepilot_task_id}")
    if request.admin_note:
        lines.append(f"备注：{request.admin_note}")
    if request.logs:
        latest_log = request.logs[0]
        lines.append(f"最近操作：{latest_log.to_status.value} by {latest_log.operator}")
    return "\n".join(lines)


def build_stats_text(
    *,
    total_requests: int,
    status_counts: dict[RequestStatus, int],
    recent_created: int,
    recent_finished: int,
    oldest_pending: Request | None,
) -> str:
    lines = [
        "请求统计：",
        f"总请求：{total_requests}",
        f"待处理：{status_counts.get(RequestStatus.pending, 0)}",
        f"已批准：{status_counts.get(RequestStatus.approved, 0)}",
        f"已提交到 MoviePilot：{status_counts.get(RequestStatus.submitted_to_moviepilot, 0)}",
        f"下载中：{status_counts.get(RequestStatus.downloading, 0)}",
        f"整理中：{status_counts.get(RequestStatus.organizing, 0)}",
        f"已完成：{status_counts.get(RequestStatus.finished, 0)}",
        f"处理失败：{status_counts.get(RequestStatus.failed, 0)}",
        f"已拒绝：{status_counts.get(RequestStatus.rejected, 0)}",
        f"近 24 小时新增：{recent_created}",
        f"近 24 小时完成：{recent_finished}",
    ]
    if oldest_pending is not None:
        lines.append(f"最早待处理：{format_pending_request_line(oldest_pending)}")
    return "\n".join(lines)


def get_request_for_admin(db, request_ref: str) -> Request | None:  # noqa: ANN001
    return (
        db.query(Request)
        .options(joinedload(Request.user), joinedload(Request.logs))
        .filter(build_request_lookup_filter(request_ref))
        .first()
    )


def ensure_bot_admin(user: User) -> None:
    if user.role != UserRole.admin:
        raise PermissionError("仅管理员可使用该命令。")


async def sync_request_notifications_once(application: Application) -> None:
    settings = get_settings()
    ensure_database()
    moviepilot_service = MoviePilotService(settings)

    with database.SessionLocal() as db:
        items = (
            db.query(Request)
            .options(joinedload(Request.user))
            .filter(
                Request.finished_notified_at.is_(None),
                Request.status.in_(tuple(SYNCABLE_STATUSES | {RequestStatus.finished})),
            )
            .order_by(Request.updated_at.asc())
            .all()
        )

        for item in items:
            if item.status in SYNCABLE_STATUSES:
                await sync_request_status(db, item, moviepilot_service)
                db.refresh(item)

            if item.status != RequestStatus.finished or item.finished_notified_at is not None:
                continue

            notification_text = build_finished_notification_text(item)
            requester_notified = item.requester_finished_notified_at is not None
            chat_notified = item.notification_chat_id is None or item.chat_finished_notified_at is not None

            if not requester_notified and item.user is not None:
                requester_notified = await send_telegram_message(
                    settings,
                    chat_id=item.user.tg_user_id,
                    text=notification_text,
                )
                if requester_notified:
                    item.requester_finished_notified_at = datetime.now(timezone.utc)

            if not chat_notified and item.notification_chat_id is not None:
                try:
                    await application.bot.send_message(
                        chat_id=item.notification_chat_id,
                        text=notification_text,
                        message_thread_id=item.notification_message_thread_id,
                    )
                    chat_notified = True
                    item.chat_finished_notified_at = datetime.now(timezone.utc)
                except Exception:
                    logger.exception("Failed to send finished group notification for request %s", item.id)

            if requester_notified and chat_notified:
                item.finished_notified_at = datetime.now(timezone.utc)
            db.commit()


async def request_notification_loop(application: Application) -> None:
    while True:
        try:
            await sync_request_notifications_once(application)
        except Exception:
            logger.exception("Request notification loop failed")

        await asyncio.sleep(max(get_settings().request_sync_interval_seconds, 15))


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "欢迎来到 MoviePilot 求片系统。\n"
        "你可以直接用 /search 搜索，也可以点下面按钮打开 MiniApp。",
        reply_markup=build_webapp_keyboard(),
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "/start - 打开欢迎页\n"
        "/search 片名 - 搜索候选影片\n"
        "/request 片名 - 快速发起手动求片\n"
        "/my - 查看最近请求\n"
        "/pending [数量] [状态] [关键词] - 查看请求列表，默认待审批（管理员）\n"
        "/stats - 查看请求统计（管理员）\n"
        "/detail 123 - 查看请求详情，也可回复带请求 ID 的消息使用（管理员）\n"
        "/approve 123 [备注] - 批准并提交请求，也可回复带请求 ID 的消息使用（管理员）\n"
        "/reject 123 [原因] - 拒绝请求，也可回复带请求 ID 的消息使用（管理员）\n"
        "群里直接发 TMDb 链接，我会自动识别并帮你查库/建单"
    )


async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = " ".join(context.args).strip()
    if not query:
        await update.message.reply_text("用法：/search 流浪地球")
        return

    service = MoviePilotService(get_settings())
    results = await service.search(query)
    if not results:
        await update.message.reply_text("没有找到候选结果，可以试试换个关键词。")
        return

    lines = []
    for item in results[:5]:
        year = f" ({item.year})" if item.year else ""
        lines.append(f"- {item.title}{year} [{item.media_type}]")
    await update.message.reply_text("搜索结果：\n" + "\n".join(lines))


async def request_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    title = " ".join(context.args).strip()
    if not title:
        await update.message.reply_text("用法：/request 影片名")
        return

    telegram_user = update.effective_user
    if telegram_user is None:
        await update.message.reply_text("无法识别 Telegram 用户信息。")
        return

    settings = get_settings()
    ensure_database()

    with database.SessionLocal() as db:
        user = upsert_user(
            db,
            TelegramProfileIn(
                id=telegram_user.id,
                username=telegram_user.username,
                first_name=telegram_user.first_name,
                last_name=telegram_user.last_name,
            ),
            settings,
        )
        existing_request = find_existing_active_request(
            db,
            source_id=f"manual:{title.lower()}",
            media_type=MediaType.movie,
        )
        if existing_request is not None:
            await update.message.reply_text(
                f"《{title}》已经有进行中的请求了。\n"
                f"当前状态：{existing_request.status.value}\n"
                f"请求 ID：{format_request_reference(existing_request)}"
            )
            return
        request = build_request_from_item(
            user_id=user.id,
            item_title=title,
            item_media_type=MediaType.movie.value,
            item_source="manual",
            item_source_id=f"manual:{title.lower()}",
            item_overview="Created from Telegram /request command.",
            item_poster_url=None,
            item_year=None,
            status=RequestStatus.pending if settings.require_admin_approval else RequestStatus.approved,
        )
        db.add(request)
        db.flush()
        add_request_log(
            db,
            request,
            from_status=None,
            to_status=request.status,
            operator=f"bot:{user.tg_user_id}",
            note="Created from Telegram bot quick request.",
        )
        db.commit()
        await update.message.reply_text(f"已创建请求：{title}\n当前状态：{request.status.value}")


async def my_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    telegram_user = update.effective_user
    if telegram_user is None:
        await update.message.reply_text("无法识别 Telegram 用户信息。")
        return

    ensure_database()

    with database.SessionLocal() as db:
        items = (
            db.query(Request)
            .join(Request.user)
            .options(joinedload(Request.user))
            .filter(Request.user.has(tg_user_id=telegram_user.id))
            .order_by(Request.created_at.desc())
            .limit(5)
            .all()
        )

    if not items:
        await update.message.reply_text("你还没有任何求片记录。")
        return

    lines = [f"- {item.title}: {item.status.value}" for item in items]
    await update.message.reply_text("最近 5 条请求：\n" + "\n".join(lines))


async def pending_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    telegram_user = update.effective_user
    if message is None or telegram_user is None:
        return

    limit, status, keyword = parse_pending_filters(context.args)
    if limit is None:
        await message.reply_text(
            "用法：/pending [数量] [状态] [关键词]\n"
            "示例：/pending 20、/pending failed、/pending Batman、/pending 20 finished Batman"
        )
        return

    settings = get_settings()
    ensure_database()

    with database.SessionLocal() as db:
        admin_user = upsert_user(db, build_profile_from_telegram_user(telegram_user), settings)
        try:
            ensure_bot_admin(admin_user)
        except PermissionError as exc:
            await message.reply_text(str(exc))
            return

        items = (
            db.query(Request)
            .options(joinedload(Request.user))
        )
        if status is not None:
            items = items.filter(Request.status == status)
        if keyword:
            keyword_pattern = f"%{keyword}%"
            items = items.filter(Request.title.ilike(keyword_pattern))
        if status == RequestStatus.pending:
            items = items.order_by(Request.created_at.asc())
        else:
            items = items.order_by(Request.updated_at.desc(), Request.created_at.desc())
        items = items.limit(limit).all()

    if not items:
        if status == RequestStatus.pending and not keyword:
            await message.reply_text("当前没有待审批请求。")
        else:
            status_label = "全部" if status is None else STATUS_LABELS.get(status, status.value)
            await message.reply_text(
                f"没有找到匹配的请求。\n状态：{status_label}" + (f"\n关键词：{keyword}" if keyword else "")
            )
        return

    lines = [f"{format_pending_request_line(item)}\n{build_request_action_hint(item)}" for item in items]
    await message.reply_text(build_pending_response_header(status=status, keyword=keyword, limit=limit) + "\n".join(lines))


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    telegram_user = update.effective_user
    if message is None or telegram_user is None:
        return

    settings = get_settings()
    ensure_database()
    recent_cutoff = datetime.now(timezone.utc) - timedelta(hours=24)

    with database.SessionLocal() as db:
        admin_user = upsert_user(db, build_profile_from_telegram_user(telegram_user), settings)
        try:
            ensure_bot_admin(admin_user)
        except PermissionError as exc:
            await message.reply_text(str(exc))
            return

        total_requests = db.query(func.count(Request.id)).scalar() or 0
        grouped_counts = (
            db.query(Request.status, func.count(Request.id))
            .group_by(Request.status)
            .all()
        )
        status_counts = {status: count for status, count in grouped_counts}
        recent_created = (
            db.query(func.count(Request.id))
            .filter(Request.created_at >= recent_cutoff)
            .scalar()
            or 0
        )
        recent_finished = (
            db.query(func.count(Request.id))
            .filter(
                Request.status == RequestStatus.finished,
                Request.finished_at.is_not(None),
                Request.finished_at >= recent_cutoff,
            )
            .scalar()
            or 0
        )
        oldest_pending = (
            db.query(Request)
            .options(joinedload(Request.user))
            .filter(Request.status == RequestStatus.pending)
            .order_by(Request.created_at.asc())
            .first()
        )

    await message.reply_text(
        build_stats_text(
            total_requests=total_requests,
            status_counts=status_counts,
            recent_created=recent_created,
            recent_finished=recent_finished,
            oldest_pending=oldest_pending,
        )
    )


async def detail_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    telegram_user = update.effective_user
    if message is None or telegram_user is None:
        return

    request_ref, _ = resolve_request_command_args(message, context.args)
    if not request_ref:
        await message.reply_text("用法：/detail 123，或回复一条带请求 ID 的消息后发送 /detail")
        return

    settings = get_settings()
    ensure_database()

    with database.SessionLocal() as db:
        admin_user = upsert_user(db, build_profile_from_telegram_user(telegram_user), settings)
        try:
            ensure_bot_admin(admin_user)
        except PermissionError as exc:
            await message.reply_text(str(exc))
            return

        request = get_request_for_admin(db, request_ref)
        if request is None:
            await message.reply_text(f"没有找到请求：{request_ref}")
            return

    await message.reply_text(build_request_detail_text(request))


async def approve_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    telegram_user = update.effective_user
    if message is None or telegram_user is None:
        return

    request_ref, note = resolve_request_command_args(message, context.args)
    if not request_ref:
        await message.reply_text("用法：/approve 123 [备注]，或回复一条带请求 ID 的消息后发送 /approve [备注]")
        return

    settings = get_settings()
    ensure_database()

    with database.SessionLocal() as db:
        admin_user = upsert_user(db, build_profile_from_telegram_user(telegram_user), settings)
        try:
            ensure_bot_admin(admin_user)
        except PermissionError as exc:
            await message.reply_text(str(exc))
            return

        request = get_request_for_admin(db, request_ref)
        if request is None:
            await message.reply_text(f"没有找到请求：{request_ref}")
            return

        if request.status not in {RequestStatus.pending, RequestStatus.failed, RequestStatus.approved}:
            await message.reply_text(f"请求当前状态为 {request.status.value}，不能直接批准。")
            return

        if request.status != RequestStatus.approved:
            transition_request_status(
                db,
                request,
                RequestStatus.approved,
                operator=build_bot_operator(admin_user),
                note=note or "Approved by admin via Telegram bot.",
            )

        service = MoviePilotService(settings)
        try:
            await submit_request_to_moviepilot(
                db,
                request,
                service,
                operator=build_bot_operator(admin_user),
            )
        except MoviePilotError as exc:
            transition_request_status(
                db,
                request,
                RequestStatus.failed,
                operator=build_bot_operator(admin_user),
                note=build_submission_failure_message(exc),
            )

        db.commit()
        db.refresh(request)
        await notify_request_user(settings, request)
        await notify_request_chat(settings, request)

    await message.reply_text(
        f"已批准 {format_media_label(request.title, request.media_type, request.year)}。\n"
        f"当前状态：{request.status.value}\n"
        f"请求 ID：{format_request_reference(request)}"
        + (f"\n任务：{request.moviepilot_task_id}" if request.moviepilot_task_id else "")
        + (f"\n备注：{request.admin_note}" if request.admin_note else "")
    )


async def reject_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    telegram_user = update.effective_user
    if message is None or telegram_user is None:
        return

    request_ref, note = resolve_request_command_args(message, context.args)
    if not request_ref:
        await message.reply_text("用法：/reject 123 [原因]，或回复一条带请求 ID 的消息后发送 /reject [原因]")
        return

    settings = get_settings()
    ensure_database()

    with database.SessionLocal() as db:
        admin_user = upsert_user(db, build_profile_from_telegram_user(telegram_user), settings)
        try:
            ensure_bot_admin(admin_user)
        except PermissionError as exc:
            await message.reply_text(str(exc))
            return

        request = get_request_for_admin(db, request_ref)
        if request is None:
            await message.reply_text(f"没有找到请求：{request_ref}")
            return

        if request.status in {RequestStatus.rejected, RequestStatus.finished}:
            await message.reply_text(f"请求当前状态为 {request.status.value}，不能直接拒绝。")
            return

        transition_request_status(
            db,
            request,
            RequestStatus.rejected,
            operator=build_bot_operator(admin_user),
            note=note or "Rejected by admin via Telegram bot.",
        )
        db.commit()
        db.refresh(request)
        await notify_request_user(settings, request)
        await notify_request_chat(settings, request)

    await message.reply_text(
        f"已拒绝 {format_media_label(request.title, request.media_type, request.year)}。\n"
        f"当前状态：{request.status.value}\n"
        f"请求 ID：{format_request_reference(request)}"
        + (f"\n备注：{request.admin_note}" if request.admin_note else "")
    )


async def handle_tmdb_link_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    chat = update.effective_chat
    telegram_user = update.effective_user
    if message is None or telegram_user is None or telegram_user.is_bot:
        return

    raw_text = (message.text or message.caption or "").strip()
    if not raw_text:
        return

    links = extract_tmdb_links(raw_text)
    if not links:
        return

    link = links[0]
    settings = get_settings()
    ensure_database()
    service = MoviePilotService(settings)

    try:
        item = await service.resolve_media(link.source_id, link.media_type)
    except MoviePilotError as exc:
        await message.reply_text(f"TMDb 链接识别失败：{exc}")
        return

    with database.SessionLocal() as db:
        user = upsert_user(
            db,
            TelegramProfileIn(
                id=telegram_user.id,
                username=telegram_user.username,
                first_name=telegram_user.first_name,
                last_name=telegram_user.last_name,
            ),
            settings,
        )

        existing_match = find_existing_active_request(
            db,
            source_id=item.source_id,
            media_type=item.media_type,
        )
        existing_request = None
        if existing_match is not None:
            existing_request = (
                db.query(Request)
                .join(Request.user)
                .options(joinedload(Request.user))
                .filter(Request.id == existing_match.id)
                .first()
            )
        if existing_request is not None:
            await message.reply_text(
                f"识别到 {format_media_label(item.title, item.media_type, item.year)}。\n"
                f"这个条目已经有请求了，当前状态：{existing_request.status.value}\n"
                f"发起人：{existing_request.user.nickname}\n"
                f"请求 ID：{format_request_reference(existing_request)}"
            )
            return

        request = build_request_from_item(
            user_id=user.id,
            item_title=item.title,
            item_media_type=item.media_type,
            item_source=item.source,
            item_source_id=item.source_id,
            item_overview=item.overview,
            item_poster_url=item.poster_url,
            item_year=item.year,
            status=RequestStatus.pending if settings.require_admin_approval else RequestStatus.approved,
        )
        if chat and chat.type in {"group", "supergroup"}:
            request.notification_chat_id = chat.id
            request.notification_message_id = getattr(message, "message_id", None)
            request.notification_message_thread_id = getattr(message, "message_thread_id", None)

        availability = await service.inspect_media(request)
        if availability.exists_in_library:
            await message.reply_text(
                f"识别到 {format_media_label(item.title, item.media_type, item.year)}。\n"
                "MoviePilot 库里已经有这条内容了，不再重复提交。"
            )
            return

        if availability.has_subscription:
            await message.reply_text(
                f"识别到 {format_media_label(item.title, item.media_type, item.year)}。\n"
                f"MoviePilot 已经存在订阅：{availability.subscription_id}。\n"
                "这条内容已经在处理链路里了。"
            )
            return

        db.add(request)
        db.flush()
        add_request_log(
            db,
            request,
            from_status=None,
            to_status=request.status,
            operator=f"bot:{user.tg_user_id}",
            note="Created from Telegram TMDb link.",
        )

        if not settings.require_admin_approval:
            try:
                await submit_request_to_moviepilot(
                    db,
                    request,
                    service,
                    operator=f"bot:{user.tg_user_id}",
                )
            except MoviePilotError as exc:
                transition_request_status(
                    db,
                    request,
                    RequestStatus.failed,
                    operator=f"bot:{user.tg_user_id}",
                    note=build_submission_failure_message(exc),
                )

        db.commit()

        if request.status == RequestStatus.pending:
            await message.reply_text(
                f"识别到 {format_media_label(item.title, item.media_type, item.year)}。\n"
                f"已创建求片请求，当前状态：{request.status.value}\n"
                f"请求 ID：{format_request_reference(request)}"
            )
        else:
            await message.reply_text(
                f"识别到 {format_media_label(item.title, item.media_type, item.year)}。\n"
                f"已直接提交到 MoviePilot，当前状态：{request.status.value}\n"
                f"任务：{request.moviepilot_task_id or format_request_reference(request)}"
            )


def build_application() -> Application:
    settings = get_settings()
    if not settings.telegram_bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is required to run the bot.")

    application = Application.builder().token(settings.telegram_bot_token).build()
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("search", search_command))
    application.add_handler(CommandHandler("request", request_command))
    application.add_handler(CommandHandler("my", my_command))
    application.add_handler(CommandHandler("pending", pending_command))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(CommandHandler("detail", detail_command))
    application.add_handler(CommandHandler("approve", approve_command))
    application.add_handler(CommandHandler("reject", reject_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_tmdb_link_message))
    return application


async def main() -> None:
    settings = get_settings()
    database.configure_database(settings.database_url)
    database.init_database()

    application = build_application()
    await application.initialize()
    await application.start()
    await application.updater.start_polling()
    notification_task = asyncio.create_task(request_notification_loop(application))
    try:
        await asyncio.Event().wait()
    finally:
        notification_task.cancel()
        with suppress(asyncio.CancelledError):
            await notification_task
        await application.updater.stop()
        await application.stop()
        await application.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
