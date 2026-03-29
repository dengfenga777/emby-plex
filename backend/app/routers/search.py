from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from ..config import Settings
from ..deps import get_app_settings, get_current_user
from ..models import User
from ..schemas import SearchResponse, SearchResult
from ..services.moviepilot import MoviePilotService

router = APIRouter(tags=["search"])


@router.get("/search", response_model=SearchResponse)
async def search_media(
    q: str = Query(..., min_length=1, max_length=120),
    _: User = Depends(get_current_user),
    settings: Settings = Depends(get_app_settings),
) -> SearchResponse:
    service = MoviePilotService(settings)
    results = await service.search(q)
    return SearchResponse(items=[SearchResult(**item.as_dict()) for item in results])

