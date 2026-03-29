from __future__ import annotations

import re
from dataclasses import dataclass

from ..enums import MediaType

TMDB_LINK_RE = re.compile(
    r"https?://(?:www\.)?themoviedb\.org/(?P<kind>movie|tv)/(?P<tmdb_id>\d+)(?:[/?#][^\s]*)?",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ParsedTmdbLink:
    tmdb_id: int
    media_type: MediaType
    original_url: str

    @property
    def source_id(self) -> str:
        return f"tmdb:{self.tmdb_id}"


def extract_tmdb_links(text: str) -> list[ParsedTmdbLink]:
    links: list[ParsedTmdbLink] = []
    for match in TMDB_LINK_RE.finditer(text):
        kind = match.group("kind").lower()
        media_type = MediaType.movie if kind == "movie" else MediaType.series
        links.append(
            ParsedTmdbLink(
                tmdb_id=int(match.group("tmdb_id")),
                media_type=media_type,
                original_url=match.group(0),
            )
        )
    return links
