from __future__ import annotations

import logging

import httpx

from ..config import Settings
from ..enums import MediaType, RequestStatus
from ..models import Request
from .request_identity import format_request_reference

logger = logging.getLogger(__name__)

STATUS_LABELS: dict[RequestStatus, str] = {
    RequestStatus.pending: "待处理",
    RequestStatus.approved: "已批准",
    RequestStatus.rejected: "已拒绝",
    RequestStatus.submitted_to_moviepilot: "已提交到 MoviePilot",
    RequestStatus.downloading: "下载中",
    RequestStatus.organizing: "整理中",
    RequestStatus.finished: "已完成",
    RequestStatus.failed: "处理失败",
}


def format_media_type(media_type: MediaType | str) -> str:
    if media_type == MediaType.movie or media_type == MediaType.movie.value:
        return "电影"
    if media_type == MediaType.anime or media_type == MediaType.anime.value:
        return "动漫"
    return "剧集"


def format_media_label(title: str, media_type: MediaType | str, year: int | None) -> str:
    year_suffix = f" ({year})" if year else ""
    return f"《{title}》{year_suffix} [{format_media_type(media_type)}]"


def build_request_status_notification_text(request: Request) -> str:
    media_label = format_media_label(request.title, request.media_type, request.year)
    status_label = STATUS_LABELS.get(request.status, request.status.value)

    if request.status == RequestStatus.submitted_to_moviepilot:
        headline = f"{media_label} 已通过审批，正在进入处理链路。"
    elif request.status == RequestStatus.downloading:
        headline = f"{media_label} 已通过审批，并开始下载。"
    elif request.status == RequestStatus.rejected:
        headline = f"{media_label} 已被管理员拒绝。"
    elif request.status == RequestStatus.finished:
        headline = f"{media_label} 已确认在库或已完成。"
    elif request.status == RequestStatus.failed:
        headline = f"{media_label} 处理失败，需要重新介入。"
    else:
        headline = f"{media_label} 状态已更新。"

    lines = [
        headline,
        f"当前状态：{status_label}",
        f"请求 ID：{format_request_reference(request)}",
    ]
    if request.admin_note:
        lines.append(f"备注：{request.admin_note}")
    if request.moviepilot_task_id:
        lines.append(f"任务：{request.moviepilot_task_id}")
    return "\n".join(lines)


def build_finished_notification_text(request: Request) -> str:
    requester = request.user.nickname if request.user else f"user:{request.user_id}"
    lines = [
        f"{format_media_label(request.title, request.media_type, request.year)} 已入库。",
        f"当前状态：{STATUS_LABELS.get(request.status, request.status.value)}",
        f"发起人：{requester}",
        f"请求 ID：{format_request_reference(request)}",
    ]
    if request.moviepilot_task_id:
        lines.append(f"任务：{request.moviepilot_task_id}")
    if request.admin_note:
        lines.append(f"备注：{request.admin_note}")
    return "\n".join(lines)


def build_batch_summary_text(
    *,
    action_label: str,
    processed_count: int,
    skipped_count: int,
    processed_ids: list[str],
) -> str:
    lines = [
        f"{action_label} 已完成。",
        f"成功处理：{processed_count} 条",
        f"跳过：{skipped_count} 条",
    ]
    if processed_ids:
        lines.append("处理请求：" + ", ".join(processed_ids[:8]))
    return "\n".join(lines)


async def send_telegram_message(
    settings: Settings,
    *,
    chat_id: int,
    text: str,
    message_thread_id: int | None = None,
    reply_to_message_id: int | None = None,
) -> bool:
    if not settings.telegram_bot_token:
        logger.info("Skip Telegram notification because TELEGRAM_BOT_TOKEN is not configured.")
        return False

    payload: dict[str, object] = {
        "chat_id": chat_id,
        "text": text,
    }
    if message_thread_id is not None:
        payload["message_thread_id"] = message_thread_id
    if reply_to_message_id is not None:
        payload["reply_parameters"] = {"message_id": reply_to_message_id}

    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
        return True
    except Exception:
        logger.exception("Failed to send Telegram notification to chat %s", chat_id)
        return False
