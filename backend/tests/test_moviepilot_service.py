from __future__ import annotations

from typing import Any

import pytest

from app.config import Settings
from app.enums import MediaType, RequestStatus
from app.models import Request
from app.services.moviepilot import MoviePilotService


class StubMoviePilotService(MoviePilotService):
    def __init__(
        self,
        settings: Settings,
        responses: dict[tuple[str, str], Any],
    ):
        super().__init__(settings)
        self.responses = responses

    async def _request_json(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
    ) -> Any:
        handler = self.responses[(method, path)]
        if callable(handler):
            return handler(params=params, json=json, data=data)
        return handler


def build_settings() -> Settings:
    return Settings(
        moviepilot_mode="api",
        moviepilot_base_url="http://moviepilot.local:3001",
        moviepilot_api_key="secret-token",
    )


def build_request(**overrides: Any) -> Request:
    payload = {
        "user_id": 1,
        "title": "The Batman",
        "media_type": MediaType.movie,
        "source": "tmdb",
        "source_id": "tmdb:748783",
        "overview": "Bruce Wayne confronts corruption in Gotham.",
        "poster_url": "https://example.com/poster.jpg",
        "year": 2022,
        "status": RequestStatus.pending,
    }
    payload.update(overrides)
    return Request(**payload)


@pytest.mark.asyncio
async def test_api_search_maps_moviepilot_results() -> None:
    service = StubMoviePilotService(
        build_settings(),
        {
            ("GET", "/media/search"): [
                {
                    "title": "The Batman",
                    "type": "电影",
                    "year": "2022",
                    "tmdb_id": 748783,
                    "overview": "Bruce Wayne confronts corruption in Gotham.",
                    "poster_path": "https://example.com/poster.jpg",
                }
            ]
        },
    )

    results = await service.search("Batman")

    assert len(results) == 1
    assert results[0].source == "tmdb"
    assert results[0].source_id == "tmdb:748783"
    assert results[0].media_type == "movie"
    assert results[0].year == 2022


@pytest.mark.asyncio
async def test_resolve_media_maps_moviepilot_detail_payload() -> None:
    service = StubMoviePilotService(
        build_settings(),
        {
            ("GET", "/media/tmdb%3A1399"): {
                "title": "权力的游戏",
                "original_title": "Game of Thrones",
                "year": "2011",
                "type": "电视剧",
                "tmdb_id": 1399,
                "overview": "Seven kingdoms fight for the throne.",
                "poster_path": "https://example.com/got.jpg",
            }
        },
    )

    result = await service.resolve_media("tmdb:1399", MediaType.series)

    assert result.source == "tmdb"
    assert result.source_id == "tmdb:1399"
    assert result.title == "权力的游戏"
    assert result.media_type == "series"
    assert result.year == 2011


@pytest.mark.asyncio
async def test_create_task_finishes_when_media_already_exists() -> None:
    service = StubMoviePilotService(
        build_settings(),
        {
            ("GET", "/mediaserver/exists"): {
                "success": True,
                "data": {"item": {"id": "library-item-1"}},
            }
        },
    )

    result = await service.create_task(build_request())

    assert result.status == RequestStatus.finished
    assert result.task_id == "library:library-item-1"


@pytest.mark.asyncio
async def test_create_task_creates_subscription_payload_for_series() -> None:
    captured: dict[str, Any] = {}

    def handle_subscribe_create(
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        captured["json"] = json
        return {"success": True, "data": {"id": 42}, "message": "ok"}

    service = StubMoviePilotService(
        build_settings(),
        {
            ("GET", "/mediaserver/exists"): {"success": False, "data": {"item": {}}},
            ("GET", "/subscribe/media/tmdb%3A1399"): {},
            ("POST", "/subscribe/"): handle_subscribe_create,
        },
    )

    request = build_request(
        title="Game of Thrones",
        media_type=MediaType.series,
        source_id="tmdb:1399",
        year=2011,
    )

    result = await service.create_task(request)

    assert result.status == RequestStatus.submitted_to_moviepilot
    assert result.task_id == "subscribe:42"
    assert captured["json"]["name"] == "Game of Thrones"
    assert captured["json"]["type"] == "电视剧"
    assert captured["json"]["mediaid"] == "tmdb:1399"
    assert captured["json"]["tmdbid"] == 1399


@pytest.mark.asyncio
async def test_inspect_media_reports_existing_subscription() -> None:
    service = StubMoviePilotService(
        build_settings(),
        {
            ("GET", "/mediaserver/exists"): {"success": False, "data": {"item": {}}},
            ("GET", "/subscribe/media/tmdb%3A1399"): {
                "id": 77,
                "name": "Game of Thrones",
                "mediaid": "tmdb:1399",
            },
        },
    )

    availability = await service.inspect_media(
        build_request(
            title="Game of Thrones",
            media_type=MediaType.series,
            source_id="tmdb:1399",
            year=2011,
        )
    )

    assert availability.exists_in_library is False
    assert availability.has_subscription is True
    assert availability.subscription_id == "77"


@pytest.mark.asyncio
async def test_search_resources_maps_moviepilot_context_payloads() -> None:
    service = StubMoviePilotService(
        build_settings(),
        {
            ("GET", "/search/media/tmdb%3A748783"): {
                "success": True,
                "data": [
                    {
                        "meta_info": {
                            "title": "The Batman 2022 2160p BluRay x265",
                            "subtitle": "新蝙蝠侠",
                            "resource_type": "BluRay",
                            "resource_pix": "2160p",
                            "video_encode": "x265",
                            "audio_encode": "DTS",
                        },
                        "torrent_info": {
                            "site_name": "M-Team",
                            "title": "The Batman 2022 2160p BluRay x265",
                            "description": "新蝙蝠侠",
                            "size": 12345,
                            "seeders": 9,
                            "peers": 1,
                            "grabs": 88,
                            "downloadvolumefactor": 0,
                            "uploadvolumefactor": 1,
                            "hit_and_run": False,
                            "volume_factor": "FREE",
                            "pubdate": "2024-01-01 00:00:00",
                            "page_url": "https://example.com/torrent/1",
                            "labels": ["中字", "4k"],
                        },
                        "media_info": {
                            "title": "The Batman",
                            "original_title": "The Batman",
                            "year": "2022",
                            "tmdb_id": 748783,
                        },
                    }
                ],
            }
        },
    )

    items = await service.search_resources(build_request())

    assert len(items) == 1
    assert items[0].site_name == "M-Team"
    assert items[0].resource_type == "BluRay"
    assert items[0].resource_pix == "2160p"
    assert items[0].labels == ["中字", "4k"]
    assert items[0].download_volume_factor == 0
    assert items[0].recommendation is not None
    assert items[0].score > 0
    assert items[0].media_payload["tmdb_id"] == 748783


@pytest.mark.asyncio
async def test_download_resource_posts_selected_candidate() -> None:
    captured: dict[str, Any] = {}

    def handle_download(
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        captured["json"] = json
        return {"success": True, "message": "download added", "data": {"hash": "abc123"}}

    service = StubMoviePilotService(
        build_settings(),
        {
            ("POST", "/download/"): handle_download,
        },
    )

    result = await service.download_resource(
        build_request(),
        media_payload={"title": "The Batman", "year": "2022", "tmdb_id": 748783},
        torrent_payload={"title": "The Batman 2022 2160p BluRay", "site_name": "M-Team"},
    )

    assert result.status == RequestStatus.downloading
    assert result.task_id == "download:abc123"
    assert captured["json"]["media_in"]["tmdb_id"] == 748783
    assert captured["json"]["torrent_in"]["site_name"] == "M-Team"


@pytest.mark.asyncio
async def test_search_resources_keeps_source_order_and_still_scores_candidates() -> None:
    service = StubMoviePilotService(
        build_settings(),
        {
            ("GET", "/search/media/tmdb%3A748783"): {
                "success": True,
                "data": [
                    {
                        "meta_info": {
                            "title": "The Batman 2022 1080p WEB-DL",
                            "resource_type": "WEB-DL",
                            "resource_pix": "1080p",
                        },
                        "torrent_info": {
                            "site_name": "Site A",
                            "title": "The Batman 2022 1080p WEB-DL",
                            "seeders": 120,
                            "grabs": 500,
                            "downloadvolumefactor": 1,
                        },
                        "media_info": {
                            "title": "The Batman",
                            "year": "2022",
                            "tmdb_id": 748783,
                        },
                    },
                    {
                        "meta_info": {
                            "title": "The Batman 2022 2160p BluRay",
                            "resource_type": "BluRay",
                            "resource_pix": "2160p",
                        },
                        "torrent_info": {
                            "site_name": "Site B",
                            "title": "The Batman 2022 2160p BluRay",
                            "seeders": 20,
                            "grabs": 80,
                            "downloadvolumefactor": 0,
                            "labels": ["中字"],
                        },
                        "media_info": {
                            "title": "The Batman",
                            "year": "2022",
                            "tmdb_id": 748783,
                        },
                    },
                ],
            }
        },
    )

    items = await service.search_resources(build_request())

    assert len(items) == 2
    assert items[0].site_name == "Site A"
    assert items[1].site_name == "Site B"
    assert items[1].score > items[0].score
