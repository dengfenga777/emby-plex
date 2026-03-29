from __future__ import annotations

from dataclasses import dataclass

from ..enums import MediaType


@dataclass
class MoviePilotSearchItem:
    source_id: str
    source: str
    title: str
    media_type: str
    year: int | None = None
    overview: str | None = None
    poster_url: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "source_id": self.source_id,
            "source": self.source,
            "title": self.title,
            "media_type": MediaType(self.media_type),
            "year": self.year,
            "overview": self.overview,
            "poster_url": self.poster_url,
        }
