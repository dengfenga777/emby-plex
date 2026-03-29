from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends

from ..config import Settings
from ..deps import get_app_settings

router = APIRouter(tags=["health"])


@router.get("/health")
def healthcheck(settings: Settings = Depends(get_app_settings)) -> dict[str, str]:
    return {
        "status": "ok",
        "mode": settings.moviepilot_mode,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

