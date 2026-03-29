from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from datetime import datetime, timezone

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, WebAppInfo
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters
from sqlalchemy.orm import joinedload

from . import database
from .config import get_settings
from .enums import MediaType, RequestStatus
from .models import Request
from .schemas import TelegramProfileIn
from .services.auth import upsert_user
from .services.request_identity import format_request_reference
from .services.moviepilot import MoviePilotError, MoviePilotService
from .services.request_workflow import (
    SYNCABLE_STATUSES,
    add_request_log,
    build_submission_failure_message,
    submit_request_to_moviepilot,
    sync_request_status,
    transition_request_status,
)
from .services.tmdb_links import extract_tmdb_links

ACTIVE_REQUEST_STATUSES = {
    RequestStatus.pending,
    RequestStatus.approved,
    RequestStatus.submitted_to_moviepilot,
    RequestStatus.downloading,
    RequestStatus.organizing,
    RequestStatus.finished,
}

logger = logging.getLogger(__name__)


def build_webapp_keyboard() -> InlineKeyboardMarkup:
    settings = get_settings()
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("打开 MiniApp", web_app=WebAppInfo(url=settings.telegram_webapp_url))]]
    )


def format_media_type(media_type: MediaType | str) -> str:
    if media_type == MediaType.movie or media_type == MediaType.movie.value:
        return "电影"
    if media_type == MediaType.anime or media_type == MediaType.anime.value:
        return "动漫"
    return "剧集"


def format_media_label(title: str, media_type: MediaType | str, year: int | None) -> str:
    year_suffix = f" ({year})" if year else ""
    return f"《{title}》{year_suffix} [{format_media_type(media_type)}]"


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


def build_finished_notification_text(request: Request) -> str:
    year_suffix = f" ({request.year})" if request.year else ""
    requester = request.user.nickname if request.user else f"user:{request.user_id}"
    return (
        f"《{request.title}》{year_suffix} 已入库。\n"
        f"状态：{request.status.value}\n"
        f"发起人：{requester}\n"
        f"请求 ID：{format_request_reference(request)}"
    )


async def sync_request_notifications_once(application: Application) -> None:
    settings = get_settings()
    ensure_database()
    moviepilot_service = MoviePilotService(settings)

    with database.SessionLocal() as db:
        items = (
            db.query(Request)
            .options(joinedload(Request.user))
            .filter(
                Request.notification_chat_id.is_not(None),
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

            try:
                await application.bot.send_message(
                    chat_id=item.notification_chat_id,
                    text=build_finished_notification_text(item),
                    message_thread_id=item.notification_message_thread_id,
                )
            except Exception:
                logger.exception("Failed to send finished notification for request %s", item.id)
                continue

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

        existing_request = (
            db.query(Request)
            .join(Request.user)
            .options(joinedload(Request.user))
            .filter(
                Request.source_id == item.source_id,
                Request.status.in_(ACTIVE_REQUEST_STATUSES),
            )
            .order_by(Request.created_at.desc())
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
