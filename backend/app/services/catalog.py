from __future__ import annotations

from .search_types import MoviePilotSearchItem

CATALOG: list[dict[str, object]] = [
    {
        "source_id": "tmdb:748783",
        "source": "tmdb",
        "title": "The Batman",
        "media_type": "movie",
        "year": 2022,
        "poster_url": "https://image.tmdb.org/t/p/w500/74xTEgt7R36Fpooo50r9T25onhq.jpg",
        "overview": "Bruce Wayne confronts corruption in Gotham while chasing the Riddler.",
        "aliases": ["蝙蝠侠", "新蝙蝠侠"],
    },
    {
        "source_id": "tmdb:733317",
        "source": "tmdb",
        "title": "Project Hail Mary",
        "media_type": "movie",
        "year": 2027,
        "poster_url": None,
        "overview": "An astronaut wakes up alone and must save Earth with science and nerve.",
        "aliases": ["挽救计划", "Project Hail Mary"],
    },
    {
        "source_id": "tmdb:543103",
        "source": "tmdb",
        "title": "Kimi no Na wa.",
        "media_type": "anime",
        "year": 2016,
        "poster_url": "https://image.tmdb.org/t/p/w500/q719jXXEzOoYaps6babgKnONONX.jpg",
        "overview": "Two teenagers begin swapping bodies and form a bond that transcends time.",
        "aliases": ["你的名字", "君の名は。"],
    },
    {
        "source_id": "tmdb:62177",
        "source": "tmdb",
        "title": "Bridgerton",
        "media_type": "series",
        "year": 2020,
        "poster_url": "https://image.tmdb.org/t/p/w500/zxtMlfpGw4S8xTlQnUqYX0Hn3Yl.jpg",
        "overview": "High society romance and scandal during Regency-era London.",
        "aliases": ["布里奇顿", "柏捷顿家族"],
    },
    {
        "source_id": "tmdb:10681",
        "source": "tmdb",
        "title": "Wandering Earth II",
        "media_type": "movie",
        "year": 2023,
        "poster_url": "https://image.tmdb.org/t/p/w500/pR858ihc6LsreR9gGmcl8u9n8pJ.jpg",
        "overview": "Humanity builds giant engines to move the Earth away from the Sun.",
        "aliases": ["流浪地球2"],
    },
    {
        "source_id": "tmdb:999999",
        "source": "manual",
        "title": "Three-Body",
        "media_type": "series",
        "year": 2024,
        "poster_url": None,
        "overview": "A global scientific mystery spirals into contact with an alien civilization.",
        "aliases": ["三体", "3 Body Problem"],
    },
]


def search_catalog(query: str, limit: int = 8) -> list[MoviePilotSearchItem]:
    normalized = query.strip().lower()
    if not normalized:
        return []

    matches: list[MoviePilotSearchItem] = []
    for raw_item in CATALOG:
        haystacks = [str(raw_item["title"]).lower()]
        haystacks.extend(alias.lower() for alias in raw_item.get("aliases", []))
        haystacks.append(str(raw_item.get("overview", "")).lower())
        if any(normalized in item for item in haystacks):
            matches.append(
                MoviePilotSearchItem(
                    source_id=str(raw_item["source_id"]),
                    source=str(raw_item["source"]),
                    title=str(raw_item["title"]),
                    media_type=str(raw_item["media_type"]),
                    year=raw_item.get("year"),
                    overview=raw_item.get("overview"),
                    poster_url=raw_item.get("poster_url"),
                )
            )
        if len(matches) >= limit:
            break
    return matches
