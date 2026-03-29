from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def build_client(tmp_path: Path) -> TestClient:
    database_path = tmp_path / "test.db"
    settings = Settings(
        secret_key="test-secret",
        database_url=f"sqlite:///{database_path}",
        dev_auth_enabled=True,
        require_admin_approval=True,
        default_admin_ids="1",
    )
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
