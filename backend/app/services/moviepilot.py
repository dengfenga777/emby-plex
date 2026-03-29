from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

import httpx

from ..config import Settings
from ..enums import MediaType, RequestStatus
from ..models import Request
from .catalog import CATALOG, search_catalog
from .search_types import MoviePilotSearchItem


@dataclass(frozen=True)
class MoviePilotSubmissionResult:
    task_id: str
    status: RequestStatus
    note: str | None = None


@dataclass(frozen=True)
class MoviePilotAvailabilityResult:
    library_item_id: str | None = None
    subscription_id: str | None = None
    subscription_note: str | None = None

    @property
    def exists_in_library(self) -> bool:
        return self.library_item_id is not None

    @property
    def has_subscription(self) -> bool:
        return self.subscription_id is not None


@dataclass(frozen=True)
class MoviePilotResourceCandidate:
    title: str
    subtitle: str | None
    description: str | None
    site_name: str | None
    size: float | None
    seeders: int | None
    peers: int | None
    grabs: int | None
    pubdate: str | None
    page_url: str | None
    resource_type: str | None
    resource_pix: str | None
    resource_effect: str | None
    video_encode: str | None
    audio_encode: str | None
    season_episode: str | None
    volume_factor: str | None
    download_volume_factor: float | None
    upload_volume_factor: float | None
    hit_and_run: bool | None
    recommendation: str | None
    score: int
    labels: list[str]
    media_payload: dict[str, Any]
    torrent_payload: dict[str, Any]


@dataclass(frozen=True)
class ExternalMediaIds:
    tmdbid: int | None = None
    doubanid: str | None = None
    bangumiid: int | None = None


class MoviePilotError(RuntimeError):
    pass


class MoviePilotService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._access_token: str | None = None

    async def search(self, query: str) -> list[MoviePilotSearchItem]:
        if self.settings.moviepilot_mode == "mock":
            return search_catalog(query)

        payload = await self._request_json(
            "GET",
            "/media/search",
            params={"title": query, "type": "media", "page": 1, "count": 8},
        )
        if not isinstance(payload, list):
            raise MoviePilotError("MoviePilot returned an unexpected search payload.")

        items: list[MoviePilotSearchItem] = []
        for item in payload:
            if not isinstance(item, dict):
                continue

            source, source_id = self._pick_source(item)
            if not source_id:
                continue

            items.append(
                MoviePilotSearchItem(
                    source_id=source_id,
                    source=source,
                    title=str(item.get("title") or item.get("original_title") or "Unknown"),
                    media_type=self._to_agent_media_type(item.get("type")),
                    year=self._parse_year(item.get("year")),
                    overview=item.get("overview"),
                    poster_url=item.get("poster_path"),
                )
            )

        return items

    async def create_task(self, request: Request) -> MoviePilotSubmissionResult:
        if self.settings.moviepilot_mode == "mock":
            return MoviePilotSubmissionResult(
                task_id=f"mock-task-{request.id}",
                status=RequestStatus.submitted_to_moviepilot,
                note="Request forwarded to MoviePilot mock adapter.",
            )

        library_item_id = await self._lookup_library_item(request)
        if library_item_id:
            return MoviePilotSubmissionResult(
                task_id=f"library:{library_item_id}",
                status=RequestStatus.finished,
                note="Media already exists in MoviePilot library.",
            )

        existing_subscribe = await self._lookup_subscription(request)
        if existing_subscribe:
            subscribe_id = existing_subscribe.get("id") or request.source_id
            return MoviePilotSubmissionResult(
                task_id=f"subscribe:{subscribe_id}",
                status=RequestStatus.submitted_to_moviepilot,
                note="Existing subscription found in MoviePilot.",
            )

        payload = await self._request_json(
            "POST",
            "/subscribe/",
            json=self._build_subscribe_payload(request),
        )
        if not isinstance(payload, dict):
            raise MoviePilotError("MoviePilot returned an invalid subscribe response.")
        if not payload.get("success"):
            raise MoviePilotError(payload.get("message") or "MoviePilot subscribe request failed.")

        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        task_id = data.get("id") if isinstance(data, dict) else None
        return MoviePilotSubmissionResult(
            task_id=f"subscribe:{task_id or request.source_id}",
            status=RequestStatus.submitted_to_moviepilot,
            note=payload.get("message") or "Subscription created in MoviePilot.",
        )

    async def get_task_status(self, request: Request) -> RequestStatus:
        if self.settings.moviepilot_mode == "mock":
            if request.submitted_at is None:
                return request.status

            submitted_at = request.submitted_at
            if submitted_at.tzinfo is None:
                submitted_at = submitted_at.replace(tzinfo=timezone.utc)

            elapsed_seconds = (datetime.now(timezone.utc) - submitted_at).total_seconds()
            if elapsed_seconds < 20:
                return RequestStatus.submitted_to_moviepilot
            if elapsed_seconds < 60:
                return RequestStatus.downloading
            if elapsed_seconds < 120:
                return RequestStatus.organizing
            return RequestStatus.finished

        if await self._lookup_library_item(request):
            return RequestStatus.finished
        if await self._is_in_transfer_queue(request):
            return RequestStatus.organizing
        if await self._is_downloading(request):
            return RequestStatus.downloading
        if await self._lookup_subscription(request):
            return RequestStatus.submitted_to_moviepilot
        return request.status

    async def resolve_media(self, source_id: str, media_type: MediaType) -> MoviePilotSearchItem:
        if self.settings.moviepilot_mode == "mock":
            for raw_item in CATALOG:
                if raw_item.get("source_id") == source_id:
                    return MoviePilotSearchItem(
                        source_id=str(raw_item["source_id"]),
                        source=str(raw_item["source"]),
                        title=str(raw_item["title"]),
                        media_type=str(raw_item["media_type"]),
                        year=raw_item.get("year"),
                        overview=raw_item.get("overview"),
                        poster_url=raw_item.get("poster_url"),
                    )
            raise MoviePilotError(f"Mock catalog does not contain {source_id}.")

        payload = await self._request_json(
            "GET",
            f"/media/{quote(source_id, safe='')}",
            params={"type_name": self._to_moviepilot_media_type(media_type)},
        )
        if not isinstance(payload, dict):
            raise MoviePilotError("MoviePilot returned an invalid media detail payload.")

        title = str(payload.get("title") or payload.get("original_title") or "").strip()
        if not title:
            raise MoviePilotError("MoviePilot did not return a recognizable media title.")

        source, resolved_source_id = self._pick_source(payload)
        return MoviePilotSearchItem(
            source_id=resolved_source_id or source_id,
            source=source,
            title=title,
            media_type=self._coerce_agent_media_type(payload.get("type"), media_type),
            year=self._parse_year(payload.get("year")),
            overview=payload.get("overview"),
            poster_url=payload.get("poster_path"),
        )

    async def inspect_media(self, request: Request) -> MoviePilotAvailabilityResult:
        library_item_id = await self._lookup_library_item(request)
        existing_subscribe = await self._lookup_subscription(request)
        if existing_subscribe:
            subscribe_id = existing_subscribe.get("id") or request.source_id
            note = existing_subscribe.get("name") or existing_subscribe.get("mediaid")
            return MoviePilotAvailabilityResult(
                library_item_id=library_item_id,
                subscription_id=str(subscribe_id),
                subscription_note=str(note) if note else None,
            )
        return MoviePilotAvailabilityResult(library_item_id=library_item_id)

    async def search_resources(self, request: Request) -> list[MoviePilotResourceCandidate]:
        if self.settings.moviepilot_mode == "mock":
            return []

        payload = await self._request_json(
            "GET",
            f"/search/media/{quote(request.source_id, safe='')}",
            params={
                "mtype": self._to_moviepilot_media_type(request.media_type),
                "title": request.title,
                "year": str(request.year) if request.year else None,
            },
        )
        if not isinstance(payload, dict):
            raise MoviePilotError("MoviePilot returned an invalid resource search payload.")
        if not payload.get("success"):
            raise MoviePilotError(payload.get("message") or "MoviePilot resource search failed.")

        data = payload.get("data")
        if not isinstance(data, list):
            return []

        items: list[MoviePilotResourceCandidate] = []
        for raw_item in data:
            if not isinstance(raw_item, dict):
                continue
            media_payload = raw_item.get("media_info")
            torrent_payload = raw_item.get("torrent_info")
            meta_payload = raw_item.get("meta_info")
            if not isinstance(media_payload, dict) or not isinstance(torrent_payload, dict):
                continue

            labels = torrent_payload.get("labels")
            score, recommendation = self._score_resource_candidate(
                request,
                torrent_payload=torrent_payload,
                meta_payload=meta_payload if isinstance(meta_payload, dict) else {},
                labels=labels if isinstance(labels, list) else [],
            )
            items.append(
                MoviePilotResourceCandidate(
                    title=str(
                        torrent_payload.get("title")
                        or meta_payload.get("title")
                        or request.title
                        if isinstance(meta_payload, dict)
                        else torrent_payload.get("title") or request.title
                    ),
                    subtitle=str(meta_payload.get("subtitle")) if isinstance(meta_payload, dict) and meta_payload.get("subtitle") else None,
                    description=str(torrent_payload.get("description")) if torrent_payload.get("description") else None,
                    site_name=str(torrent_payload.get("site_name")) if torrent_payload.get("site_name") else None,
                    size=float(torrent_payload.get("size")) if torrent_payload.get("size") is not None else None,
                    seeders=int(torrent_payload.get("seeders")) if torrent_payload.get("seeders") is not None else None,
                    peers=int(torrent_payload.get("peers")) if torrent_payload.get("peers") is not None else None,
                    grabs=int(torrent_payload.get("grabs")) if torrent_payload.get("grabs") is not None else None,
                    pubdate=str(torrent_payload.get("pubdate")) if torrent_payload.get("pubdate") else None,
                    page_url=str(torrent_payload.get("page_url")) if torrent_payload.get("page_url") else None,
                    resource_type=str(meta_payload.get("resource_type")) if isinstance(meta_payload, dict) and meta_payload.get("resource_type") else None,
                    resource_pix=str(meta_payload.get("resource_pix")) if isinstance(meta_payload, dict) and meta_payload.get("resource_pix") else None,
                    resource_effect=str(meta_payload.get("resource_effect")) if isinstance(meta_payload, dict) and meta_payload.get("resource_effect") else None,
                    video_encode=str(meta_payload.get("video_encode")) if isinstance(meta_payload, dict) and meta_payload.get("video_encode") else None,
                    audio_encode=str(meta_payload.get("audio_encode")) if isinstance(meta_payload, dict) and meta_payload.get("audio_encode") else None,
                    season_episode=str(meta_payload.get("season_episode")) if isinstance(meta_payload, dict) and meta_payload.get("season_episode") else None,
                    volume_factor=str(torrent_payload.get("volume_factor")) if torrent_payload.get("volume_factor") else None,
                    download_volume_factor=self._safe_float(torrent_payload.get("downloadvolumefactor")),
                    upload_volume_factor=self._safe_float(torrent_payload.get("uploadvolumefactor")),
                    hit_and_run=bool(torrent_payload.get("hit_and_run")) if torrent_payload.get("hit_and_run") is not None else None,
                    recommendation=recommendation,
                    score=score,
                    labels=[str(label) for label in labels] if isinstance(labels, list) else [],
                    media_payload=media_payload,
                    torrent_payload=torrent_payload,
                )
            )

        return items

    async def download_resource(
        self,
        request: Request,
        *,
        media_payload: dict[str, Any],
        torrent_payload: dict[str, Any],
    ) -> MoviePilotSubmissionResult:
        if self.settings.moviepilot_mode == "mock":
            return MoviePilotSubmissionResult(
                task_id=f"download:{request.id}",
                status=RequestStatus.downloading,
                note="Mock direct download task created.",
            )

        if not self._candidate_matches_request_payload(request, media_payload):
            raise MoviePilotError("Selected resource does not match the request.")

        payload = await self._request_json(
            "POST",
            "/download/",
            json={
                "media_in": media_payload,
                "torrent_in": torrent_payload,
            },
        )
        if not isinstance(payload, dict):
            raise MoviePilotError("MoviePilot returned an invalid download response.")
        if not payload.get("success"):
            raise MoviePilotError(payload.get("message") or "MoviePilot direct download failed.")

        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        task_id = data.get("hash") or data.get("id") or request.source_id
        return MoviePilotSubmissionResult(
            task_id=f"download:{task_id}",
            status=RequestStatus.downloading,
            note=payload.get("message") or "Direct download task created in MoviePilot.",
        )

    async def _request_json(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
    ) -> Any:
        url = f"{self._api_root()}{path}"
        headers = await self._build_auth_headers()

        async with httpx.AsyncClient(timeout=self.settings.moviepilot_timeout_seconds) as client:
            response = await client.request(
                method=method,
                url=url,
                params={key: value for key, value in (params or {}).items() if value is not None},
                json=json,
                data=data,
                headers=headers,
            )

        if response.status_code >= 400:
            message = self._extract_error_message(response)
            raise MoviePilotError(f"{method.upper()} {path} failed: {message}")

        return response.json()

    async def _build_auth_headers(self) -> dict[str, str]:
        if self.settings.moviepilot_api_key:
            return {"X-API-KEY": self.settings.moviepilot_api_key}

        token = await self._get_access_token()
        return {"Authorization": f"Bearer {token}"}

    async def _get_access_token(self) -> str:
        if self._access_token:
            return self._access_token

        if not self.settings.moviepilot_base_url:
            raise MoviePilotError("MOVIEPILOT_BASE_URL is required when MOVIEPILOT_MODE=api.")
        if not self.settings.moviepilot_username or not self.settings.moviepilot_password:
            raise MoviePilotError(
                "Set MOVIEPILOT_API_KEY or provide MOVIEPILOT_USERNAME/MOVIEPILOT_PASSWORD."
            )

        url = f"{self._api_root()}/login/access-token"
        form_data = {
            "username": self.settings.moviepilot_username,
            "password": self.settings.moviepilot_password,
            "grant_type": "password",
        }
        if self.settings.moviepilot_otp_password:
            form_data["otp_password"] = self.settings.moviepilot_otp_password

        async with httpx.AsyncClient(timeout=self.settings.moviepilot_timeout_seconds) as client:
            response = await client.post(url, data=form_data)

        if response.status_code >= 400:
            raise MoviePilotError(
                f"MoviePilot login failed: {self._extract_error_message(response)}"
            )

        payload = response.json()
        token = payload.get("access_token")
        if not token:
            raise MoviePilotError("MoviePilot login did not return an access_token.")
        self._access_token = token
        return token

    def _api_root(self) -> str:
        if not self.settings.moviepilot_base_url:
            raise MoviePilotError("MOVIEPILOT_BASE_URL is required when MOVIEPILOT_MODE=api.")

        base_url = self.settings.moviepilot_base_url.rstrip("/")
        if base_url.endswith("/api/v1"):
            return base_url
        return f"{base_url}/api/v1"

    def _pick_source(self, payload: dict[str, Any]) -> tuple[str, str | None]:
        if payload.get("tmdb_id"):
            return "tmdb", f"tmdb:{payload['tmdb_id']}"
        if payload.get("douban_id"):
            return "douban", f"douban:{payload['douban_id']}"
        if payload.get("bangumi_id"):
            return "bangumi", f"bangumi:{payload['bangumi_id']}"
        prefix = payload.get("mediaid_prefix")
        media_id = payload.get("media_id")
        if prefix and media_id:
            return str(prefix), f"{prefix}:{media_id}"
        source = payload.get("source")
        return str(source or "moviepilot"), None

    def _to_agent_media_type(self, raw_type: Any) -> str:
        if raw_type == "电影":
            return MediaType.movie.value
        return MediaType.series.value

    def _coerce_agent_media_type(self, raw_type: Any, fallback: MediaType) -> str:
        if raw_type in {"电影", "电视剧"}:
            return self._to_agent_media_type(raw_type)
        if fallback == MediaType.movie:
            return MediaType.movie.value
        return MediaType.series.value

    def _to_moviepilot_media_type(self, media_type: MediaType) -> str:
        if media_type == MediaType.movie:
            return "电影"
        return "电视剧"

    def _parse_year(self, raw_year: Any) -> int | None:
        if raw_year is None:
            return None
        text = str(raw_year).strip()
        if not text:
            return None
        digits = "".join(char for char in text[:4] if char.isdigit())
        return int(digits) if len(digits) == 4 else None

    def _parse_external_ids(self, source_id: str) -> ExternalMediaIds:
        if ":" not in source_id:
            return ExternalMediaIds()

        prefix, value = source_id.split(":", 1)
        if prefix == "tmdb" and value.isdigit():
            return ExternalMediaIds(tmdbid=int(value))
        if prefix == "douban":
            return ExternalMediaIds(doubanid=value)
        if prefix == "bangumi" and value.isdigit():
            return ExternalMediaIds(bangumiid=int(value))
        return ExternalMediaIds()

    def _build_subscribe_payload(self, request: Request) -> dict[str, Any]:
        external_ids = self._parse_external_ids(request.source_id)
        payload = {
            "name": request.title,
            "year": str(request.year) if request.year else None,
            "type": self._to_moviepilot_media_type(request.media_type),
            "mediaid": request.source_id,
            "tmdbid": external_ids.tmdbid,
            "doubanid": external_ids.doubanid,
            "bangumiid": external_ids.bangumiid,
            "poster": request.poster_url,
            "description": request.overview,
            "state": "R",
        }
        return {key: value for key, value in payload.items() if value not in (None, "", [])}

    async def _lookup_library_item(self, request: Request) -> str | None:
        external_ids = self._parse_external_ids(request.source_id)
        payload = await self._request_json(
            "GET",
            "/mediaserver/exists",
            params={
                "title": request.title,
                "year": str(request.year) if request.year else None,
                "mtype": self._to_moviepilot_media_type(request.media_type),
                "tmdbid": external_ids.tmdbid,
            },
        )
        if not isinstance(payload, dict) or not payload.get("success"):
            return None

        data = payload.get("data")
        if not isinstance(data, dict):
            return None
        item = data.get("item")
        if not isinstance(item, dict):
            return None
        item_id = item.get("id")
        return str(item_id) if item_id else "exists"

    async def _lookup_subscription(self, request: Request) -> dict[str, Any] | None:
        path = f"/subscribe/media/{quote(request.source_id, safe='')}"
        payload = await self._request_json(
            "GET",
            path,
            params={"title": request.title},
        )
        if not isinstance(payload, dict):
            return None
        if payload.get("id") or payload.get("name") or payload.get("mediaid") or payload.get("tmdbid"):
            return payload
        return None

    async def _is_downloading(self, request: Request) -> bool:
        payload = await self._request_json("GET", "/download/")
        if not isinstance(payload, list):
            return False
        for item in payload:
            if not isinstance(item, dict):
                continue
            if self._matches_request(item.get("media"), request):
                return True
        return False

    async def _is_in_transfer_queue(self, request: Request) -> bool:
        payload = await self._request_json("GET", "/transfer/queue")
        if not isinstance(payload, list):
            return False
        for item in payload:
            if not isinstance(item, dict):
                continue
            if self._matches_request(item.get("media"), request):
                return True
        return False

    def _matches_request(self, payload: Any, request: Request) -> bool:
        if not isinstance(payload, dict):
            return False

        external_ids = self._parse_external_ids(request.source_id)
        if external_ids.tmdbid and payload.get("tmdb_id") == external_ids.tmdbid:
            return True
        if external_ids.doubanid and str(payload.get("douban_id") or "") == external_ids.doubanid:
            return True
        if external_ids.bangumiid and payload.get("bangumi_id") == external_ids.bangumiid:
            return True

        payload_title = str(payload.get("title") or "").strip().casefold()
        request_title = request.title.strip().casefold()
        if payload_title and payload_title == request_title:
            payload_year = self._parse_year(payload.get("year"))
            return payload_year is None or request.year is None or payload_year == request.year
        return False

    def _candidate_matches_request_payload(
        self,
        request: Request,
        media_payload: dict[str, Any],
    ) -> bool:
        external_ids = self._parse_external_ids(request.source_id)
        if external_ids.tmdbid and media_payload.get("tmdb_id") == external_ids.tmdbid:
            return True
        if external_ids.doubanid and str(media_payload.get("douban_id") or "") == external_ids.doubanid:
            return True
        if external_ids.bangumiid and media_payload.get("bangumi_id") == external_ids.bangumiid:
            return True

        payload_title = str(media_payload.get("title") or media_payload.get("original_title") or "").strip().casefold()
        request_title = request.title.strip().casefold()
        if not payload_title or payload_title != request_title:
            return False

        payload_year = self._parse_year(media_payload.get("year"))
        return payload_year is None or request.year is None or payload_year == request.year

    def _score_resource_candidate(
        self,
        request: Request,
        *,
        torrent_payload: dict[str, Any],
        meta_payload: dict[str, Any],
        labels: list[Any],
    ) -> tuple[int, str | None]:
        score = 0
        reasons: list[str] = []

        download_factor = self._safe_float(torrent_payload.get("downloadvolumefactor"))
        if download_factor == 0:
            score += 45
            reasons.append("免流")
        elif download_factor is not None and download_factor <= 0.5:
            score += 24
            reasons.append("半价流量")

        if torrent_payload.get("hit_and_run") is False:
            score += 6
        elif torrent_payload.get("hit_and_run") is True:
            score -= 8
            reasons.append("H&R")

        seeders = self._safe_int(torrent_payload.get("seeders")) or 0
        grabs = self._safe_int(torrent_payload.get("grabs")) or 0
        score += min(seeders, 240) // 12
        score += min(grabs, 2000) // 250
        if seeders >= 80:
            reasons.append("高做种")

        resource_pix = str(meta_payload.get("resource_pix") or "").lower()
        if "2160" in resource_pix or "4k" in resource_pix:
            score += 12
            reasons.append("4K")
        elif "1080" in resource_pix:
            score += 7

        resource_type = str(meta_payload.get("resource_type") or "").lower()
        if "remux" in resource_type:
            score += 8
        elif "bluray" in resource_type:
            score += 6
        elif "web-dl" in resource_type:
            score += 4

        resource_effect = str(meta_payload.get("resource_effect") or "").upper()
        if "DV" in resource_effect or "DOVI" in resource_effect:
            score += 4
        if "HDR" in resource_effect:
            score += 3

        normalized_labels = {str(label).strip().lower() for label in labels}
        if "中字" in normalized_labels:
            score += 5
            reasons.append("中字")

        season_episode = str(meta_payload.get("season_episode") or "").strip().upper()
        title = str(torrent_payload.get("title") or meta_payload.get("title") or "").upper()
        if request.media_type == MediaType.series and season_episode and "COMPLETE" not in title and "全集" not in title:
            score -= 4

        recommendation = " / ".join(reasons[:3]) if reasons else "综合质量更优"
        return score, recommendation

    def _safe_float(self, value: Any) -> float | None:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _safe_int(self, value: Any) -> int | None:
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _extract_error_message(self, response: httpx.Response) -> str:
        try:
            payload = response.json()
        except ValueError:
            return response.text or response.reason_phrase

        if isinstance(payload, dict):
            return str(payload.get("detail") or payload.get("message") or response.reason_phrase)
        return response.reason_phrase
