"""Search/staging priorities for the household's existing Japanese subtitles.

Avoid brittle hard-coded filesystem paths: prefer Jellyfin Genres when present,
but also recognize movie folders named Horror, Drama, Suspense or Thriller.
Keep all other media eligible for later passes. No user-level private data here.
"""
from __future__ import annotations

import re

PREFERRED_SHOWS = {"thexfiles", "xfiles", "itsalwayssunnyinphiladelphia"}


def simplify(text):
    return re.sub(r"[^a-z0-9]+", "", str(text or "").casefold())


def priority(row):
    kind = row.get("kind")
    if kind == "Episode":
        series = simplify(row.get("series_title") or "")
        return 0 if series in PREFERRED_SHOWS else 2
    if kind == "Movie":
        genres = row.get("genres")
        genre_text = " ".join(str(x) for x in genres) if isinstance(genres, list) else ""
        path = str(row.get("host_path") or "")
        # Scope fallback folder tags to a path component; "Drama, Suspense"
        # qualifies, but a film titled "The Horror..." in another folder does not.
        parent = str(path.rsplit("/", 1)[0])
        tags = genre_text + " " + parent
        if re.search(r"(?i)(?<![a-z])horror(?![a-z])", tags):
            return 0
        if re.search(r"(?i)(?<![a-z])(?:drama|suspense|thriller)(?![a-z])", tags):
            return 1
        return 2
    return 3
