from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from app import bot
from app import database as app_database
from app.config import Settings
from app.enums import MediaType, RequestStatus, UserRole
from app.models import Request, User
from app.services.moviepilot import MoviePilotAvailabilityResult
from app.services.search_types import MoviePilotSearchItem


class FakeMoviePilotService:
    def __init__(self, settings: Settings):
        self.settings = settings

    async def resolve_media(self, source_id: str, media_type):  # noqa: ANN001
        return MoviePilotSearchItem(
            source_id=source_id,
            source="tmdb",
            title="The Batman",
            media_type="movie",
            year=2022,
            overview="Bruce Wayne confronts corruption in Gotham.",
            poster_url="https://example.com/poster.jpg",
        )

    async def inspect_media(self, request: Request) -> MoviePilotAvailabilityResult:
        return MoviePilotAvailabilityResult()


class FakeMessage:
    def __init__(self, text: str):
        self.text = text
        self.caption = None
        self.replies: list[str] = []

    async def reply_text(self, text: str, reply_markup=None) -> None:  # noqa: ANN001
        self.replies.append(text)


@pytest.mark.asyncio
async def test_tmdb_link_message_creates_pending_request(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "bot.db"
    app_database.configure_database(f"sqlite:///{database_path}")
    app_database.init_database()

    settings = Settings(
        secret_key="test-secret",
        database_url=f"sqlite:///{database_path}",
        dev_auth_enabled=False,
        require_admin_approval=True,
        default_admin_ids="647050755",
        moviepilot_mode="api",
        moviepilot_base_url="http://moviepilot.local:3001",
        moviepilot_api_key="secret-token",
        telegram_bot_token="test-bot-token",
        telegram_webapp_url="https://example.com",
    )

    monkeypatch.setattr(bot, "get_settings", lambda: settings)
    monkeypatch.setattr(bot, "MoviePilotService", FakeMoviePilotService)

    message = FakeMessage("https://www.themoviedb.org/movie/748783-the-batman")
    update = SimpleNamespace(
        effective_message=message,
        effective_chat=SimpleNamespace(id=-1001234567890, type="supergroup"),
        effective_user=SimpleNamespace(
            id=647050755,
            username="cccxx7",
            first_name="cc",
            last_name=None,
            is_bot=False,
        ),
    )

    await bot.handle_tmdb_link_message(update, None)

    assert len(message.replies) == 1
    assert "已创建求片请求" in message.replies[0]
    assert "请求 ID：1" in message.replies[0]

    with app_database.SessionLocal() as db:
        items = db.query(Request).all()
        assert len(items) == 1
        assert items[0].public_id == 1
        assert items[0].source_id == "tmdb:748783"
        assert items[0].status.value == "pending"
        assert items[0].notification_chat_id == -1001234567890


@pytest.mark.asyncio
async def test_sync_request_notifications_once_sends_finished_message(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "notify.db"
    app_database.configure_database(f"sqlite:///{database_path}")
    app_database.init_database()

    settings = Settings(
        secret_key="test-secret",
        database_url=f"sqlite:///{database_path}",
        dev_auth_enabled=False,
        require_admin_approval=True,
        default_admin_ids="647050755",
        moviepilot_mode="api",
        moviepilot_base_url="http://moviepilot.local:3001",
        moviepilot_api_key="secret-token",
        telegram_bot_token="test-bot-token",
        telegram_webapp_url="https://example.com",
    )
    monkeypatch.setattr(bot, "get_settings", lambda: settings)

    with app_database.SessionLocal() as db:
        user = User(tg_user_id=647050755, username="cccxx7", nickname="cc", role=UserRole.admin)
        db.add(user)
        db.flush()
        request = Request(
            user_id=user.id,
            title="The Batman",
            media_type=MediaType.movie,
            source="tmdb",
            source_id="tmdb:748783",
            status=RequestStatus.finished,
            year=2022,
            notification_chat_id=-1001234567890,
        )
        db.add(request)
        db.commit()

    sent: list[tuple[int, str]] = []

    class FakeBot:
        async def send_message(self, chat_id: int, text: str, message_thread_id=None) -> None:  # noqa: ANN001
            sent.append((chat_id, text))

    application = SimpleNamespace(bot=FakeBot())

    await bot.sync_request_notifications_once(application)

    assert sent
    assert sent[0][0] == -1001234567890
    assert "已入库" in sent[0][1]
    assert "请求 ID：1" in sent[0][1]

    with app_database.SessionLocal() as db:
        request = db.query(Request).first()
        assert request.public_id == 1
        assert request.finished_notified_at is not None
