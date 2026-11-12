"""Exact movie-folder scope for owner-selected Japanese subtitle sourcing.

Scope matches existing folders under BOTH known movie library roots. It does
not create folders, infer genre from a movie title, or include TV episodes.
Each stage of sourcing must filter by the same scope.
"""
from pathlib import Path
import re

SCOPE = "horror-drama-folders"
MOVIES_NO_ANIME = "movies-no-anime"
SCOPES = ("all", SCOPE, MOVIES_NO_ANIME)
ROOTS = (
    Path("/mnt/BigDisk/Video/Movies"),
    Path("/mnt/2TB/Plex Expansion/Movies"),
)
CATEGORIES = {"horror", "drama suspense", "drama", "suspense"}


def matches(row, scope="all"):
    if scope == "all":
        return True
    if scope not in (SCOPE, MOVIES_NO_ANIME):
        raise ValueError("unsupported_japanese_source_scope")
    if not isinstance(row, dict) or row.get("kind") != "Movie":
        return False
    if scope == MOVIES_NO_ANIME:
        # Anime is a specific Japanese media category. Do not exclude all
        # animation: that would also discard Western animated films.
        genres = row.get("genres") or []
        if any(isinstance(g, str) and "anime" in
               {t for t in re.split(r"[^a-z]+", g.casefold()) if t}
               for g in genres):
            return False
        value = row.get("host_path")
        if not isinstance(value, str) or not value.startswith("/"):
            return False
        path = Path(value)
        if path.is_symlink():
            return False
        # Folder names identify an Anime section; the filename (movie title)
        # must not accidentally exclude unrelated films.
        for root in ROOTS:
            try:
                relative = path.relative_to(root)
            except ValueError:
                continue
            return not any(
                "anime" in {t for t in re.split(r"[^a-z]+", part.casefold()) if t}
                for part in relative.parts[:-1])
        return True
    value = row.get("host_path")
    if not isinstance(value, str) or not value.startswith("/"):
        return False
    path = Path(value)
    if path.is_symlink():
        return False
    for root in ROOTS:
        try:
            relative = path.relative_to(root)
        except ValueError:
            continue
        if len(relative.parts) < 2:
            return False
        # Select by actual top-level movie category, not arbitrary substring
        # anywhere in the path (movie titles can include "Horror" or "Drama").
        category = re.sub(r"[^a-z]+", " ", relative.parts[0].casefold()).strip()
        return category in CATEGORIES
    return False


def select(rows, scope="all"):
    return [r for r in rows if matches(r, scope)]
