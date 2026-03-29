from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import bot
from app import database as app_database
from app.config import Settings
from app.enums import MediaType, RequestStatus, UserRole
from app.models import Request, User
from app.services.moviepilot import MoviePilotAvailabilityResult, MoviePilotSubmissionResult
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

    async def create_task(self, request: Request) -> MoviePilotSubmissionResult:
        return MoviePilotSubmissionResult(
            task_id=f"subscribe:{request.source_id}",
            status=RequestStatus.submitted_to_moviepilot,
            note="Created by fake service.",
        )


class FakeMessage:
    def __init__(self, text: str, *, reply_to_message=None, message_id: int | None = None):
        self.text = text
        self.caption = None
        self.reply_to_message = reply_to_message
        self.message_id = message_id
        self.message_thread_id = None
        self.replies: list[str] = []

    async def reply_text(self, text: str, reply_markup=None) -> None:  # noqa: ANN001
        self.replies.append(text)


def build_user(
    *,
    user_id: int,
    username: str,
    first_name: str,
    last_name: str | None = None,
    is_bot: bool = False,
):
    return SimpleNamespace(
        id=user_id,
        username=username,
        first_name=first_name,
        last_name=last_name,
        is_bot=is_bot,
    )


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

    message = FakeMessage("https://www.themoviedb.org/movie/748783-the-batman", message_id=5566)
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
        assert items[0].notification_message_id == 5566


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

    private_sent: list[tuple[int, str]] = []

    async def fake_send_telegram_message(
        settings,
        *,
        chat_id: int,
        text: str,
        message_thread_id=None,
        reply_to_message_id=None,
    ):  # noqa: ANN001
        private_sent.append((chat_id, text))
        return True

    monkeypatch.setattr(bot, "send_telegram_message", fake_send_telegram_message)

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
    assert private_sent
    assert private_sent[0][0] == 647050755
    assert "已入库" in private_sent[0][1]

    with app_database.SessionLocal() as db:
        request = db.query(Request).first()
        assert request.public_id == 1
        assert request.finished_notified_at is not None
        assert request.requester_finished_notified_at is not None
        assert request.chat_finished_notified_at is not None


@pytest.mark.asyncio
async def test_pending_command_lists_pending_requests(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "pending.db"
    app_database.configure_database(f"sqlite:///{database_path}")
    app_database.init_database()

    settings = Settings(
        secret_key="test-secret",
        database_url=f"sqlite:///{database_path}",
        dev_auth_enabled=False,
        require_admin_approval=True,
        default_admin_ids="647050755",
        moviepilot_mode="mock",
        telegram_bot_token="test-bot-token",
        telegram_webapp_url="https://example.com",
    )
    monkeypatch.setattr(bot, "get_settings", lambda: settings)

    with app_database.SessionLocal() as db:
        requester = User(tg_user_id=1001, username="viewer", nickname="Mini App", role=UserRole.user)
        db.add(requester)
        db.flush()
        db.add(
            Request(
                user_id=requester.id,
                title="The Batman",
                media_type=MediaType.movie,
                source="tmdb",
                source_id="tmdb:748783",
                status=RequestStatus.pending,
                year=2022,
            )
        )
        db.commit()

    message = FakeMessage("")
    update = SimpleNamespace(
        effective_message=message,
        effective_user=build_user(user_id=647050755, username="admin", first_name="Admin"),
    )

    await bot.pending_command(update, SimpleNamespace(args=[]))

    assert message.replies
    assert "待审批请求" in message.replies[0]
    assert "#1 The Batman" in message.replies[0]
    assert "操作：/detail 1 | /approve 1 | /reject 1" in message.replies[0]


@pytest.mark.asyncio
async def test_pending_command_supports_limit_argument(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "pending-limit.db"
    app_database.configure_database(f"sqlite:///{database_path}")
    app_database.init_database()

    settings = Settings(
        secret_key="test-secret",
        database_url=f"sqlite:///{database_path}",
        dev_auth_enabled=False,
        require_admin_approval=True,
        default_admin_ids="647050755",
        moviepilot_mode="mock",
        telegram_bot_token="test-bot-token",
        telegram_webapp_url="https://example.com",
    )
    monkeypatch.setattr(bot, "get_settings", lambda: settings)

    with app_database.SessionLocal() as db:
        requester = User(tg_user_id=1001, username="viewer", nickname="Mini App", role=UserRole.user)
        db.add(requester)
        db.flush()
        db.add(
            Request(
                user_id=requester.id,
                title="The Batman",
                media_type=MediaType.movie,
                source="tmdb",
                source_id="tmdb:748783",
                status=RequestStatus.pending,
                year=2022,
            )
        )
        db.add(
            Request(
                user_id=requester.id,
                title="Three-Body",
                media_type=MediaType.series,
                source="manual",
                source_id="manual:three-body",
                status=RequestStatus.pending,
                year=2024,
            )
        )
        db.commit()

    message = FakeMessage("")
    update = SimpleNamespace(
        effective_message=message,
        effective_user=build_user(user_id=647050755, username="admin", first_name="Admin"),
    )

    await bot.pending_command(update, SimpleNamespace(args=["1"]))

    assert message.replies
    assert "#1 The Batman" in message.replies[0]
    assert "Three-Body" not in message.replies[0]


@pytest.mark.asyncio
async def test_pending_command_supports_keyword_filter(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "pending-keyword.db"
    app_database.configure_database(f"sqlite:///{database_path}")
    app_database.init_database()

    settings = Settings(
        secret_key="test-secret",
        database_url=f"sqlite:///{database_path}",
        dev_auth_enabled=False,
        require_admin_approval=True,
        default_admin_ids="647050755",
        moviepilot_mode="mock",
        telegram_bot_token="test-bot-token",
        telegram_webapp_url="https://example.com",
    )
    monkeypatch.setattr(bot, "get_settings", lambda: settings)

    with app_database.SessionLocal() as db:
        requester = User(tg_user_id=1001, username="viewer", nickname="Mini App", role=UserRole.user)
        db.add(requester)
        db.flush()
        db.add(
            Request(
                user_id=requester.id,
                title="The Batman",
                media_type=MediaType.movie,
                source="tmdb",
                source_id="tmdb:748783",
                status=RequestStatus.pending,
                year=2022,
            )
        )
        db.add(
            Request(
                user_id=requester.id,
                title="Three-Body",
                media_type=MediaType.series,
                source="manual",
                source_id="manual:three-body",
                status=RequestStatus.pending,
                year=2024,
            )
        )
        db.commit()

    message = FakeMessage("")
    update = SimpleNamespace(
        effective_message=message,
        effective_user=build_user(user_id=647050755, username="admin", first_name="Admin"),
    )

    await bot.pending_command(update, SimpleNamespace(args=["Batman"]))

    assert message.replies
    assert "关键词：Batman" in message.replies[0]
    assert "#1 The Batman" in message.replies[0]
    assert "Three-Body" not in message.replies[0]


@pytest.mark.asyncio
async def test_pending_command_supports_status_filter(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "pending-status.db"
    app_database.configure_database(f"sqlite:///{database_path}")
    app_database.init_database()

    settings = Settings(
        secret_key="test-secret",
        database_url=f"sqlite:///{database_path}",
        dev_auth_enabled=False,
        require_admin_approval=True,
        default_admin_ids="647050755",
        moviepilot_mode="mock",
        telegram_bot_token="test-bot-token",
        telegram_webapp_url="https://example.com",
    )
    monkeypatch.setattr(bot, "get_settings", lambda: settings)

    with app_database.SessionLocal() as db:
        requester = User(tg_user_id=1001, username="viewer", nickname="Mini App", role=UserRole.user)
        db.add(requester)
        db.flush()
        db.add(
            Request(
                user_id=requester.id,
                title="The Batman",
                media_type=MediaType.movie,
                source="tmdb",
                source_id="tmdb:748783",
                status=RequestStatus.pending,
                year=2022,
            )
        )
        db.add(
            Request(
                user_id=requester.id,
                title="Dune: Part Two",
                media_type=MediaType.movie,
                source="tmdb",
                source_id="tmdb:693134",
                status=RequestStatus.failed,
                year=2024,
            )
        )
        db.commit()

    message = FakeMessage("")
    update = SimpleNamespace(
        effective_message=message,
        effective_user=build_user(user_id=647050755, username="admin", first_name="Admin"),
    )

    await bot.pending_command(update, SimpleNamespace(args=["failed"]))

    assert message.replies
    assert "状态：处理失败" in message.replies[0]
    assert "Dune: Part Two" in message.replies[0]
    assert "The Batman" not in message.replies[0]
    assert "操作：/detail 2 | /approve 2 | /reject 2" in message.replies[0]


@pytest.mark.asyncio
async def test_pending_command_supports_status_and_keyword_filter(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "pending-status-keyword.db"
    app_database.configure_database(f"sqlite:///{database_path}")
    app_database.init_database()

    settings = Settings(
        secret_key="test-secret",
        database_url=f"sqlite:///{database_path}",
        dev_auth_enabled=False,
        require_admin_approval=True,
        default_admin_ids="647050755",
        moviepilot_mode="mock",
        telegram_bot_token="test-bot-token",
        telegram_webapp_url="https://example.com",
    )
    monkeypatch.setattr(bot, "get_settings", lambda: settings)

    with app_database.SessionLocal() as db:
        requester = User(tg_user_id=1001, username="viewer", nickname="Mini App", role=UserRole.user)
        db.add(requester)
        db.flush()
        db.add(
            Request(
                user_id=requester.id,
                title="Batman Begins",
                media_type=MediaType.movie,
                source="tmdb",
                source_id="tmdb:272",
                status=RequestStatus.failed,
                year=2005,
            )
        )
        db.add(
            Request(
                user_id=requester.id,
                title="The Batman",
                media_type=MediaType.movie,
                source="tmdb",
                source_id="tmdb:748783",
                status=RequestStatus.pending,
                year=2022,
            )
        )
        db.add(
            Request(
                user_id=requester.id,
                title="Dune: Part Two",
                media_type=MediaType.movie,
                source="tmdb",
                source_id="tmdb:693134",
                status=RequestStatus.failed,
                year=2024,
            )
        )
        db.commit()

    message = FakeMessage("")
    update = SimpleNamespace(
        effective_message=message,
        effective_user=build_user(user_id=647050755, username="admin", first_name="Admin"),
    )

    await bot.pending_command(update, SimpleNamespace(args=["20", "failed", "Batman"]))

    assert message.replies
    assert "状态：处理失败" in message.replies[0]
    assert "关键词：Batman" in message.replies[0]
    assert "Batman Begins" in message.replies[0]
    assert "Dune: Part Two" not in message.replies[0]
    assert "The Batman" not in message.replies[0]


@pytest.mark.asyncio
async def test_pending_command_finished_status_shows_detail_only_action(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "pending-finished-actions.db"
    app_database.configure_database(f"sqlite:///{database_path}")
    app_database.init_database()

    settings = Settings(
        secret_key="test-secret",
        database_url=f"sqlite:///{database_path}",
        dev_auth_enabled=False,
        require_admin_approval=True,
        default_admin_ids="647050755",
        moviepilot_mode="mock",
        telegram_bot_token="test-bot-token",
        telegram_webapp_url="https://example.com",
    )
    monkeypatch.setattr(bot, "get_settings", lambda: settings)

    with app_database.SessionLocal() as db:
        requester = User(tg_user_id=1001, username="viewer", nickname="Mini App", role=UserRole.user)
        db.add(requester)
        db.flush()
        db.add(
            Request(
                user_id=requester.id,
                title="The Batman",
                media_type=MediaType.movie,
                source="tmdb",
                source_id="tmdb:748783",
                status=RequestStatus.finished,
                year=2022,
            )
        )
        db.commit()

    message = FakeMessage("")
    update = SimpleNamespace(
        effective_message=message,
        effective_user=build_user(user_id=647050755, username="admin", first_name="Admin"),
    )

    await bot.pending_command(update, SimpleNamespace(args=["finished"]))

    assert message.replies
    assert "状态：已完成" in message.replies[0]
    assert "操作：/detail 1" in message.replies[0]
    assert "/approve 1" not in message.replies[0]
    assert "/reject 1" not in message.replies[0]


@pytest.mark.asyncio
async def test_stats_command_shows_request_summary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "stats.db"
    app_database.configure_database(f"sqlite:///{database_path}")
    app_database.init_database()

    settings = Settings(
        secret_key="test-secret",
        database_url=f"sqlite:///{database_path}",
        dev_auth_enabled=False,
        require_admin_approval=True,
        default_admin_ids="647050755",
        moviepilot_mode="mock",
        telegram_bot_token="test-bot-token",
        telegram_webapp_url="https://example.com",
    )
    monkeypatch.setattr(bot, "get_settings", lambda: settings)

    now = datetime.now(timezone.utc)

    with app_database.SessionLocal() as db:
        requester = User(tg_user_id=1001, username="viewer", nickname="Mini App", role=UserRole.user)
        db.add(requester)
        db.flush()
        db.add(
            Request(
                user_id=requester.id,
                title="The Batman",
                media_type=MediaType.movie,
                source="tmdb",
                source_id="tmdb:748783",
                status=RequestStatus.pending,
                year=2022,
                created_at=now - timedelta(hours=3),
                updated_at=now - timedelta(hours=3),
            )
        )
        db.add(
            Request(
                user_id=requester.id,
                title="Dune: Part Two",
                media_type=MediaType.movie,
                source="tmdb",
                source_id="tmdb:693134",
                status=RequestStatus.failed,
                year=2024,
                created_at=now - timedelta(hours=2),
                updated_at=now - timedelta(hours=1),
            )
        )
        db.add(
            Request(
                user_id=requester.id,
                title="Three-Body",
                media_type=MediaType.series,
                source="manual",
                source_id="manual:three-body",
                status=RequestStatus.finished,
                year=2024,
                created_at=now - timedelta(hours=10),
                updated_at=now - timedelta(hours=1),
                finished_at=now - timedelta(hours=1),
            )
        )
        db.commit()

    message = FakeMessage("")
    update = SimpleNamespace(
        effective_message=message,
        effective_user=build_user(user_id=647050755, username="admin", first_name="Admin"),
    )

    await bot.stats_command(update, SimpleNamespace(args=[]))

    assert message.replies
    assert "请求统计：" in message.replies[0]
    assert "总请求：3" in message.replies[0]
    assert "待处理：1" in message.replies[0]
    assert "处理失败：1" in message.replies[0]
    assert "已完成：1" in message.replies[0]
    assert "近 24 小时新增：3" in message.replies[0]
    assert "近 24 小时完成：1" in message.replies[0]
    assert "最早待处理：#1 The Batman" in message.replies[0]


@pytest.mark.asyncio
async def test_detail_command_shows_request_detail(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "detail.db"
    app_database.configure_database(f"sqlite:///{database_path}")
    app_database.init_database()

    settings = Settings(
        secret_key="test-secret",
        database_url=f"sqlite:///{database_path}",
        dev_auth_enabled=False,
        require_admin_approval=True,
        default_admin_ids="647050755",
        moviepilot_mode="mock",
        telegram_bot_token="test-bot-token",
        telegram_webapp_url="https://example.com",
    )
    monkeypatch.setattr(bot, "get_settings", lambda: settings)

    with app_database.SessionLocal() as db:
        requester = User(tg_user_id=1001, username="viewer", nickname="Mini App", role=UserRole.user)
        db.add(requester)
        db.flush()
        request = Request(
            user_id=requester.id,
            title="The Batman",
            media_type=MediaType.movie,
            source="tmdb",
            source_id="tmdb:748783",
            status=RequestStatus.pending,
            year=2022,
            admin_note="等待管理员确认",
        )
        db.add(request)
        db.commit()

    message = FakeMessage("")
    update = SimpleNamespace(
        effective_message=message,
        effective_user=build_user(user_id=647050755, username="admin", first_name="Admin"),
    )

    await bot.detail_command(update, SimpleNamespace(args=["1"]))

    assert message.replies
    assert "请求 ID：1" in message.replies[0]
    assert "发起人：Mini App" in message.replies[0]
    assert "备注：等待管理员确认" in message.replies[0]


@pytest.mark.asyncio
async def test_detail_command_supports_reply_message_lookup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "detail-reply.db"
    app_database.configure_database(f"sqlite:///{database_path}")
    app_database.init_database()

    settings = Settings(
        secret_key="test-secret",
        database_url=f"sqlite:///{database_path}",
        dev_auth_enabled=False,
        require_admin_approval=True,
        default_admin_ids="647050755",
        moviepilot_mode="mock",
        telegram_bot_token="test-bot-token",
        telegram_webapp_url="https://example.com",
    )
    monkeypatch.setattr(bot, "get_settings", lambda: settings)

    with app_database.SessionLocal() as db:
        requester = User(tg_user_id=1001, username="viewer", nickname="Mini App", role=UserRole.user)
        db.add(requester)
        db.flush()
        request = Request(
            user_id=requester.id,
            title="The Batman",
            media_type=MediaType.movie,
            source="tmdb",
            source_id="tmdb:748783",
            status=RequestStatus.pending,
            year=2022,
        )
        db.add(request)
        db.commit()

    replied_message = FakeMessage("已创建求片请求，当前状态：pending\n请求 ID：1")
    message = FakeMessage("", reply_to_message=replied_message)
    update = SimpleNamespace(
        effective_message=message,
        effective_user=build_user(user_id=647050755, username="admin", first_name="Admin"),
    )

    await bot.detail_command(update, SimpleNamespace(args=[]))

    assert message.replies
    assert "请求 ID：1" in message.replies[0]
    assert "当前状态：" in message.replies[0]


@pytest.mark.asyncio
async def test_approve_command_submits_request_and_notifies_requester(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "approve.db"
    app_database.configure_database(f"sqlite:///{database_path}")
    app_database.init_database()

    settings = Settings(
        secret_key="test-secret",
        database_url=f"sqlite:///{database_path}",
        dev_auth_enabled=False,
        require_admin_approval=True,
        default_admin_ids="647050755",
        moviepilot_mode="mock",
        telegram_bot_token="test-bot-token",
        telegram_webapp_url="https://example.com",
    )
    monkeypatch.setattr(bot, "get_settings", lambda: settings)
    monkeypatch.setattr(bot, "MoviePilotService", FakeMoviePilotService)

    sent: list[tuple[int, str]] = []

    async def fake_send_telegram_message(
        settings,
        *,
        chat_id: int,
        text: str,
        message_thread_id=None,
        reply_to_message_id=None,
    ):  # noqa: ANN001
        sent.append((chat_id, text))
        return True

    monkeypatch.setattr(bot, "send_telegram_message", fake_send_telegram_message)

    with app_database.SessionLocal() as db:
        requester = User(tg_user_id=1001, username="viewer", nickname="Mini App", role=UserRole.user)
        db.add(requester)
        db.flush()
        db.add(
            Request(
                user_id=requester.id,
                title="The Batman",
                media_type=MediaType.movie,
                source="tmdb",
                source_id="tmdb:748783",
                status=RequestStatus.pending,
                year=2022,
            )
        )
        db.commit()

    message = FakeMessage("")
    update = SimpleNamespace(
        effective_message=message,
        effective_user=build_user(user_id=647050755, username="admin", first_name="Admin"),
    )

    await bot.approve_command(update, SimpleNamespace(args=["1", "通过"] ))

    assert message.replies
    assert "已批准" in message.replies[0]
    assert "任务：subscribe:tmdb:748783" in message.replies[0]
    assert "备注：Created by fake service." in message.replies[0]
    assert sent
    assert sent[0][0] == 1001
    assert "已通过审批" in sent[0][1]

    with app_database.SessionLocal() as db:
        request = db.query(Request).first()
        assert request.status == RequestStatus.submitted_to_moviepilot
        assert request.moviepilot_task_id == "subscribe:tmdb:748783"


@pytest.mark.asyncio
async def test_approve_command_replies_back_to_original_group_message(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "approve-group-reply.db"
    app_database.configure_database(f"sqlite:///{database_path}")
    app_database.init_database()

    settings = Settings(
        secret_key="test-secret",
        database_url=f"sqlite:///{database_path}",
        dev_auth_enabled=False,
        require_admin_approval=True,
        default_admin_ids="647050755",
        moviepilot_mode="mock",
        telegram_bot_token="test-bot-token",
        telegram_webapp_url="https://example.com",
    )
    monkeypatch.setattr(bot, "get_settings", lambda: settings)
    monkeypatch.setattr(bot, "MoviePilotService", FakeMoviePilotService)

    sent: list[tuple[int, str, int | None, int | None]] = []

    async def fake_send_telegram_message(
        settings,
        *,
        chat_id: int,
        text: str,
        message_thread_id=None,
        reply_to_message_id=None,
    ):  # noqa: ANN001
        sent.append((chat_id, text, message_thread_id, reply_to_message_id))
        return True

    monkeypatch.setattr(bot, "send_telegram_message", fake_send_telegram_message)

    with app_database.SessionLocal() as db:
        requester = User(tg_user_id=1001, username="viewer", nickname="Mini App", role=UserRole.user)
        db.add(requester)
        db.flush()
        db.add(
            Request(
                user_id=requester.id,
                title="The Batman",
                media_type=MediaType.movie,
                source="tmdb",
                source_id="tmdb:748783",
                status=RequestStatus.pending,
                year=2022,
                notification_chat_id=-1001234567890,
                notification_message_id=321,
                notification_message_thread_id=99,
            )
        )
        db.commit()

    message = FakeMessage("")
    update = SimpleNamespace(
        effective_message=message,
        effective_user=build_user(user_id=647050755, username="admin", first_name="Admin"),
    )

    await bot.approve_command(update, SimpleNamespace(args=["1"]))

    assert len(sent) == 2
    assert sent[1][0] == -1001234567890
    assert "已通过审批" in sent[1][1]
    assert sent[1][2] == 99
    assert sent[1][3] == 321


@pytest.mark.asyncio
async def test_approve_command_supports_reply_message_with_note(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "approve-reply.db"
    app_database.configure_database(f"sqlite:///{database_path}")
    app_database.init_database()

    settings = Settings(
        secret_key="test-secret",
        database_url=f"sqlite:///{database_path}",
        dev_auth_enabled=False,
        require_admin_approval=True,
        default_admin_ids="647050755",
        moviepilot_mode="mock",
        telegram_bot_token="test-bot-token",
        telegram_webapp_url="https://example.com",
    )
    monkeypatch.setattr(bot, "get_settings", lambda: settings)
    monkeypatch.setattr(bot, "MoviePilotService", FakeMoviePilotService)

    sent: list[tuple[int, str]] = []

    async def fake_send_telegram_message(
        settings,
        *,
        chat_id: int,
        text: str,
        message_thread_id=None,
        reply_to_message_id=None,
    ):  # noqa: ANN001
        sent.append((chat_id, text))
        return True

    monkeypatch.setattr(bot, "send_telegram_message", fake_send_telegram_message)

    with app_database.SessionLocal() as db:
        requester = User(tg_user_id=1001, username="viewer", nickname="Mini App", role=UserRole.user)
        db.add(requester)
        db.flush()
        db.add(
            Request(
                user_id=requester.id,
                title="The Batman",
                media_type=MediaType.movie,
                source="tmdb",
                source_id="tmdb:748783",
                status=RequestStatus.pending,
                year=2022,
            )
        )
        db.commit()

    replied_message = FakeMessage("识别到《The Batman》。\n请求 ID：1")
    message = FakeMessage("", reply_to_message=replied_message)
    update = SimpleNamespace(
        effective_message=message,
        effective_user=build_user(user_id=647050755, username="admin", first_name="Admin"),
    )

    await bot.approve_command(update, SimpleNamespace(args=["加急处理"]))

    assert message.replies
    assert "已批准" in message.replies[0]
    assert "请求 ID：1" in message.replies[0]
    assert sent
    assert sent[0][0] == 1001

    with app_database.SessionLocal() as db:
        request = db.query(Request).first()
        assert request.status == RequestStatus.submitted_to_moviepilot
        assert request.moviepilot_task_id == "subscribe:tmdb:748783"


@pytest.mark.asyncio
async def test_reject_command_rejects_request_and_notifies_requester(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "reject.db"
    app_database.configure_database(f"sqlite:///{database_path}")
    app_database.init_database()

    settings = Settings(
        secret_key="test-secret",
        database_url=f"sqlite:///{database_path}",
        dev_auth_enabled=False,
        require_admin_approval=True,
        default_admin_ids="647050755",
        moviepilot_mode="mock",
        telegram_bot_token="test-bot-token",
        telegram_webapp_url="https://example.com",
    )
    monkeypatch.setattr(bot, "get_settings", lambda: settings)

    sent: list[tuple[int, str]] = []

    async def fake_send_telegram_message(
        settings,
        *,
        chat_id: int,
        text: str,
        message_thread_id=None,
        reply_to_message_id=None,
    ):  # noqa: ANN001
        sent.append((chat_id, text))
        return True

    monkeypatch.setattr(bot, "send_telegram_message", fake_send_telegram_message)

    with app_database.SessionLocal() as db:
        requester = User(tg_user_id=1001, username="viewer", nickname="Mini App", role=UserRole.user)
        db.add(requester)
        db.flush()
        db.add(
            Request(
                user_id=requester.id,
                title="The Batman",
                media_type=MediaType.movie,
                source="tmdb",
                source_id="tmdb:748783",
                status=RequestStatus.pending,
                year=2022,
            )
        )
        db.commit()

    message = FakeMessage("")
    update = SimpleNamespace(
        effective_message=message,
        effective_user=build_user(user_id=647050755, username="admin", first_name="Admin"),
    )

    await bot.reject_command(update, SimpleNamespace(args=["1", "资源不符合要求"]))

    assert message.replies
    assert "已拒绝" in message.replies[0]
    assert "备注：资源不符合要求" in message.replies[0]
    assert sent
    assert sent[0][0] == 1001
    assert "已被管理员拒绝" in sent[0][1]

    with app_database.SessionLocal() as db:
        request = db.query(Request).first()
        assert request.status == RequestStatus.rejected


@pytest.mark.asyncio
async def test_reject_command_replies_back_to_original_group_message(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "reject-group-reply.db"
    app_database.configure_database(f"sqlite:///{database_path}")
    app_database.init_database()

    settings = Settings(
        secret_key="test-secret",
        database_url=f"sqlite:///{database_path}",
        dev_auth_enabled=False,
        require_admin_approval=True,
        default_admin_ids="647050755",
        moviepilot_mode="mock",
        telegram_bot_token="test-bot-token",
        telegram_webapp_url="https://example.com",
    )
    monkeypatch.setattr(bot, "get_settings", lambda: settings)

    sent: list[tuple[int, str, int | None, int | None]] = []

    async def fake_send_telegram_message(
        settings,
        *,
        chat_id: int,
        text: str,
        message_thread_id=None,
        reply_to_message_id=None,
    ):  # noqa: ANN001
        sent.append((chat_id, text, message_thread_id, reply_to_message_id))
        return True

    monkeypatch.setattr(bot, "send_telegram_message", fake_send_telegram_message)

    with app_database.SessionLocal() as db:
        requester = User(tg_user_id=1001, username="viewer", nickname="Mini App", role=UserRole.user)
        db.add(requester)
        db.flush()
        db.add(
            Request(
                user_id=requester.id,
                title="The Batman",
                media_type=MediaType.movie,
                source="tmdb",
                source_id="tmdb:748783",
                status=RequestStatus.pending,
                year=2022,
                notification_chat_id=-1001234567890,
                notification_message_id=654,
                notification_message_thread_id=100,
            )
        )
        db.commit()

    message = FakeMessage("")
    update = SimpleNamespace(
        effective_message=message,
        effective_user=build_user(user_id=647050755, username="admin", first_name="Admin"),
    )

    await bot.reject_command(update, SimpleNamespace(args=["1", "资源不符合要求"]))

    assert len(sent) == 2
    assert sent[1][0] == -1001234567890
    assert "已被管理员拒绝" in sent[1][1]
    assert sent[1][2] == 100
    assert sent[1][3] == 654


@pytest.mark.asyncio
async def test_reject_command_supports_reply_message_with_reason(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "reject-reply.db"
    app_database.configure_database(f"sqlite:///{database_path}")
    app_database.init_database()

    settings = Settings(
        secret_key="test-secret",
        database_url=f"sqlite:///{database_path}",
        dev_auth_enabled=False,
        require_admin_approval=True,
        default_admin_ids="647050755",
        moviepilot_mode="mock",
        telegram_bot_token="test-bot-token",
        telegram_webapp_url="https://example.com",
    )
    monkeypatch.setattr(bot, "get_settings", lambda: settings)

    sent: list[tuple[int, str]] = []

    async def fake_send_telegram_message(
        settings,
        *,
        chat_id: int,
        text: str,
        message_thread_id=None,
        reply_to_message_id=None,
    ):  # noqa: ANN001
        sent.append((chat_id, text))
        return True

    monkeypatch.setattr(bot, "send_telegram_message", fake_send_telegram_message)

    with app_database.SessionLocal() as db:
        requester = User(tg_user_id=1001, username="viewer", nickname="Mini App", role=UserRole.user)
        db.add(requester)
        db.flush()
        db.add(
            Request(
                user_id=requester.id,
                title="The Batman",
                media_type=MediaType.movie,
                source="tmdb",
                source_id="tmdb:748783",
                status=RequestStatus.pending,
                year=2022,
            )
        )
        db.commit()

    replied_message = FakeMessage("待审批请求详情\n请求 ID：1")
    message = FakeMessage("", reply_to_message=replied_message)
    update = SimpleNamespace(
        effective_message=message,
        effective_user=build_user(user_id=647050755, username="admin", first_name="Admin"),
    )

    await bot.reject_command(update, SimpleNamespace(args=["资源质量太差"]))

    assert message.replies
    assert "已拒绝" in message.replies[0]
    assert "请求 ID：1" in message.replies[0]
    assert sent
    assert sent[0][0] == 1001

    with app_database.SessionLocal() as db:
        request = db.query(Request).first()
        assert request.status == RequestStatus.rejected
