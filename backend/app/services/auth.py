from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timezone
from urllib.parse import parse_qsl

from fastapi import HTTPException, status
from itsdangerous import BadSignature, BadTimeSignature, URLSafeTimedSerializer
from sqlalchemy.orm import Session

from ..config import Settings
from ..enums import UserRole
from ..models import User
from ..schemas import AuthSessionRequest, TelegramProfileIn


SESSION_SALT = "moviepilot-request-session"
MAX_SESSION_AGE_SECONDS = 60 * 60 * 24 * 7
MAX_TELEGRAM_AUTH_AGE_SECONDS = 60 * 60 * 24


def build_nickname(profile: TelegramProfileIn) -> str:
    parts = [item for item in [profile.first_name, profile.last_name] if item]
    if parts:
        return " ".join(parts)
    if profile.username:
        return profile.username
    return f"tg-{profile.id}"


def get_session_serializer(settings: Settings) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(settings.secret_key, salt=SESSION_SALT)


def issue_session_token(user: User, settings: Settings) -> str:
    serializer = get_session_serializer(settings)
    return serializer.dumps({"user_id": user.id})


def decode_session_token(token: str, settings: Settings) -> dict[str, int]:
    serializer = get_session_serializer(settings)
    try:
        payload = serializer.loads(token, max_age=MAX_SESSION_AGE_SECONDS)
    except (BadSignature, BadTimeSignature) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired or invalid.",
        ) from exc
    return payload


def validate_telegram_init_data(init_data: str, bot_token: str) -> TelegramProfileIn:
    params = dict(parse_qsl(init_data, keep_blank_values=True))
    provided_hash = params.pop("hash", None)
    if not provided_hash:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Telegram initData is missing hash.",
        )

    data_check_string = "\n".join(f"{key}={value}" for key, value in sorted(params.items()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()
    calculated_hash = hmac.new(
        secret_key,
        data_check_string.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(calculated_hash, provided_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Telegram initData validation failed.",
        )

    auth_date_raw = params.get("auth_date")
    if auth_date_raw:
        auth_date = datetime.fromtimestamp(int(auth_date_raw), tz=timezone.utc)
        age = (datetime.now(timezone.utc) - auth_date).total_seconds()
        if age > MAX_TELEGRAM_AUTH_AGE_SECONDS:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Telegram initData has expired.",
            )

    user_payload = params.get("user")
    if not user_payload:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Telegram initData does not contain a user payload.",
        )

    parsed_user = json.loads(user_payload)
    return TelegramProfileIn(
        id=parsed_user["id"],
        username=parsed_user.get("username"),
        first_name=parsed_user.get("first_name"),
        last_name=parsed_user.get("last_name"),
    )


def upsert_user(db: Session, profile: TelegramProfileIn, settings: Settings) -> User:
    user = db.query(User).filter(User.tg_user_id == profile.id).first()
    role = UserRole.admin if profile.id in settings.admin_id_set else UserRole.user
    nickname = build_nickname(profile)

    if user is None:
        user = User(
            tg_user_id=profile.id,
            username=profile.username,
            nickname=nickname,
            role=role,
        )
        db.add(user)
    else:
        user.username = profile.username
        user.nickname = nickname
        user.role = role

    db.commit()
    db.refresh(user)
    return user


def authenticate_session(
    db: Session,
    payload: AuthSessionRequest,
    settings: Settings,
) -> tuple[str, User, str]:
    if payload.init_data:
        if not settings.telegram_bot_token:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="TELEGRAM_BOT_TOKEN is required for Telegram WebApp authentication.",
            )
        profile = validate_telegram_init_data(payload.init_data, settings.telegram_bot_token)
        auth_mode = "telegram"
    elif settings.dev_auth_enabled and payload.profile:
        profile = payload.profile
        auth_mode = "development"
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide Telegram initData or enable development auth with a profile payload.",
        )

    user = upsert_user(db, profile, settings)
    token = issue_session_token(user, settings)
    return token, user, auth_mode

