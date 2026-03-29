from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import Settings, get_settings
from .database import configure_database, init_database
from .routers import admin, auth, health, requests, search


def create_app(settings: Settings | None = None) -> FastAPI:
    app_settings = settings or get_settings()
    configure_database(app_settings.database_url)
    init_database()

    app = FastAPI(title=app_settings.app_name)
    app.state.settings = app_settings

    allowed_origins = list(dict.fromkeys(app_settings.cors_origins + [app_settings.telegram_webapp_url]))
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_methods=["*"],
        allow_headers=["*"],
        allow_credentials=True,
    )

    app.include_router(health.router, prefix=app_settings.api_prefix)
    app.include_router(auth.router, prefix=app_settings.api_prefix)
    app.include_router(search.router, prefix=app_settings.api_prefix)
    app.include_router(requests.router, prefix=app_settings.api_prefix)
    app.include_router(admin.router, prefix=app_settings.api_prefix)
    return app


app = create_app()

