from __future__ import annotations

from app.enums import MediaType
from app.services.tmdb_links import extract_tmdb_links


def test_extract_tmdb_links_supports_movie_and_tv() -> None:
    links = extract_tmdb_links(
        "看看这个 https://www.themoviedb.org/movie/748783-the-garfield-movie "
        "还有这个 https://www.themoviedb.org/tv/1399-game-of-thrones"
    )

    assert len(links) == 2
    assert links[0].tmdb_id == 748783
    assert links[0].media_type == MediaType.movie
    assert links[0].source_id == "tmdb:748783"
    assert links[1].tmdb_id == 1399
    assert links[1].media_type == MediaType.series
    assert links[1].source_id == "tmdb:1399"
