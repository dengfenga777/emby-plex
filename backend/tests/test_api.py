from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.services.moviepilot import MoviePilotAvailabilityResult


def build_client(tmp_path: Path, **overrides: object) -> TestClient:
    database_path = tmp_path / "test.db"
    payload: dict[str, object] = {
        "secret_key": "test-secret",
        "database_url": f"sqlite:///{database_path}",
        "dev_auth_enabled": True,
        "require_admin_approval": True,
        "default_admin_ids": "1",
        "moviepilot_mode": "mock",
    }
    payload.update(overrides)
    settings = Settings(**payload)
    app = create_app(settings)
    return TestClient(app)


def authenticate(client: TestClient, profile: dict[str, object]) -> tuple[str, dict[str, object]]:
    response = client.post("/api/auth/telegram", json={"profile": profile})
    assert response.status_code == 200
    payload = response.json()
    return payload["token"], payload["user"]


def test_request_lifecycle(tmp_path: Path) -> None:
    client = build_client(tmp_path)
    user_token, _ = authenticate(
        client,
        {"id": 1001, "username": "viewer", "first_name": "Mini", "last_name": "App"},
    )
    admin_token, _ = authenticate(
        client,
        {"id": 1, "username": "admin", "first_name": "Admin", "last_name": "User"},
    )

    search_response = client.get(
        "/api/search",
        params={"q": "earth"},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert search_response.status_code == 200
    items = search_response.json()["items"]
    assert items

    create_response = client.post(
        "/api/requests",
        json=items[0],
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert create_response.status_code == 201
    assert create_response.json()["public_id"] == 1
    request_id = create_response.json()["id"]
    public_request_id = str(create_response.json()["public_id"])
    assert create_response.json()["status"] == "pending"

    admin_list_response = client.get(
        "/api/admin/requests",
        params={"status": "pending"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert admin_list_response.status_code == 200
    assert len(admin_list_response.json()) == 1
    assert admin_list_response.json()[0]["public_id"] == 1

    approve_response = client.post(
        f"/api/admin/requests/{public_request_id}/approve",
        json={"note": "Looks good"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert approve_response.status_code == 200
    assert approve_response.json()["status"] == "submitted_to_moviepilot"

    detail_response = client.get(
        f"/api/requests/{public_request_id}",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert detail_response.status_code == 200
    assert detail_response.json()["id"] == request_id
    assert detail_response.json()["public_id"] == 1
    assert detail_response.json()["status"] in {
        "submitted_to_moviepilot",
        "downloading",
        "organizing",
        "finished",
    }


def test_duplicate_request_reuses_active_request(tmp_path: Path) -> None:
    client = build_client(tmp_path)
    owner_token, owner_user = authenticate(
        client,
        {"id": 1001, "username": "viewer", "first_name": "Mini", "last_name": "App"},
    )
    another_token, _ = authenticate(
        client,
        {"id": 1002, "username": "viewer2", "first_name": "Second", "last_name": "User"},
    )

    search_response = client.get(
        "/api/search",
        params={"q": "earth"},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert search_response.status_code == 200
    item = search_response.json()["items"][0]

    first_response = client.post(
        "/api/requests",
        json=item,
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert first_response.status_code == 201
    assert first_response.json()["request_reused"] is False

    second_response = client.post(
        "/api/requests",
        json=item,
        headers={"Authorization": f"Bearer {another_token}"},
    )
    assert second_response.status_code == 200
    assert second_response.json()["request_reused"] is True
    assert second_response.json()["id"] == first_response.json()["id"]
    assert second_response.json()["public_id"] == first_response.json()["public_id"]
    assert second_response.json()["user"]["id"] == owner_user["id"]

    owner_requests_response = client.get(
        "/api/my/requests",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert owner_requests_response.status_code == 200
    assert len(owner_requests_response.json()) == 1

    another_requests_response = client.get(
        "/api/my/requests",
        headers={"Authorization": f"Bearer {another_token}"},
    )
    assert another_requests_response.status_code == 200
    assert another_requests_response.json() == []


def test_request_creation_marks_finished_when_media_already_exists(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.routers import requests as requests_router

    async def fake_inspect_media(self, request):  # noqa: ANN001
        return MoviePilotAvailabilityResult(library_item_id="library-item-1")

    monkeypatch.setattr(requests_router.MoviePilotService, "inspect_media", fake_inspect_media)

    client = build_client(tmp_path, moviepilot_mode="api")
    user_token, _ = authenticate(
        client,
        {"id": 1001, "username": "viewer", "first_name": "Mini", "last_name": "App"},
    )

    search_response = client.get(
        "/api/search",
        params={"q": "earth"},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert search_response.status_code == 200
    item = search_response.json()["items"][0]

    create_response = client.post(
        "/api/requests",
        json=item,
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert create_response.status_code == 201
    payload = create_response.json()
    assert payload["request_reused"] is False
    assert payload["status"] == "finished"
    assert payload["moviepilot_task_id"] == "library:library-item-1"
    assert payload["logs"][0]["to_status"] == "finished"


def test_request_creation_uses_existing_subscription(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.routers import requests as requests_router

    async def fake_inspect_media(self, request):  # noqa: ANN001
        return MoviePilotAvailabilityResult(
            subscription_id="sub-77",
            subscription_note="Game of Thrones",
        )

    monkeypatch.setattr(requests_router.MoviePilotService, "inspect_media", fake_inspect_media)

    client = build_client(tmp_path, moviepilot_mode="api")
    user_token, _ = authenticate(
        client,
        {"id": 1001, "username": "viewer", "first_name": "Mini", "last_name": "App"},
    )

    search_response = client.get(
        "/api/search",
        params={"q": "earth"},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert search_response.status_code == 200
    item = search_response.json()["items"][0]

    create_response = client.post(
        "/api/requests",
        json=item,
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert create_response.status_code == 201
    payload = create_response.json()
    assert payload["request_reused"] is False
    assert payload["status"] == "submitted_to_moviepilot"
    assert payload["moviepilot_task_id"] == "subscribe:sub-77"
    assert "Existing subscription found in MoviePilot" in (payload["admin_note"] or "")


def test_admin_batch_subscribe_processes_multiple_requests(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.routers import admin as admin_router

    sent: list[tuple[int, str]] = []

    async def fake_send_telegram_message(settings, *, chat_id: int, text: str, message_thread_id=None):  # noqa: ANN001
        sent.append((chat_id, text))
        return True

    monkeypatch.setattr(admin_router, "send_telegram_message", fake_send_telegram_message)

    client = build_client(tmp_path)
    user_token, _ = authenticate(
        client,
        {"id": 1001, "username": "viewer", "first_name": "Mini", "last_name": "App"},
    )
    admin_token, _ = authenticate(
        client,
        {"id": 1, "username": "admin", "first_name": "Admin", "last_name": "User"},
    )

    request_ids: list[str] = []
    for query in ("batman", "three"):
        search_response = client.get(
            "/api/search",
            params={"q": query},
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert search_response.status_code == 200
        item = search_response.json()["items"][0]
        create_response = client.post(
            "/api/requests",
            json=item,
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert create_response.status_code == 201
        request_ids.append(create_response.json()["id"])

    batch_response = client.post(
        "/api/admin/batch/requests/subscribe",
        json={"request_ids": request_ids, "note": "Batch approved"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert batch_response.status_code == 200
    payload = batch_response.json()
    assert payload["processed_count"] == 2
    assert payload["skipped_count"] == 0
    assert len(payload["items"]) == 2
    assert all(item["status"] == "submitted_to_moviepilot" for item in payload["items"])
    assert len(sent) == 3
    assert any("批量通过 已完成" in text for _, text in sent)


def test_admin_batch_reject_reports_skipped_items(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.routers import admin as admin_router

    sent: list[tuple[int, str]] = []

    async def fake_send_telegram_message(settings, *, chat_id: int, text: str, message_thread_id=None):  # noqa: ANN001
        sent.append((chat_id, text))
        return True

    monkeypatch.setattr(admin_router, "send_telegram_message", fake_send_telegram_message)

    client = build_client(tmp_path)
    user_token, _ = authenticate(
        client,
        {"id": 1001, "username": "viewer", "first_name": "Mini", "last_name": "App"},
    )
    admin_token, _ = authenticate(
        client,
        {"id": 1, "username": "admin", "first_name": "Admin", "last_name": "User"},
    )

    search_response = client.get(
        "/api/search",
        params={"q": "batman"},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert search_response.status_code == 200
    item = search_response.json()["items"][0]

    create_response = client.post(
        "/api/requests",
        json=item,
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert create_response.status_code == 201
    request_id = create_response.json()["id"]

    batch_response = client.post(
        "/api/admin/batch/requests/reject",
        json={"request_ids": [request_id, "999999"], "note": "Batch rejected"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert batch_response.status_code == 200
    payload = batch_response.json()
    assert payload["processed_count"] == 1
    assert payload["skipped_count"] == 1
    assert payload["items"][0]["status"] == "rejected"
    assert payload["skipped"][0]["request_id"] == "999999"
    assert len(sent) == 2
    assert any("批量拒绝 已完成" in text for _, text in sent)
