"""Exact movie-folder scope for owner-selected Japanese subtitle sourcing.

Scope matches existing folders under BOTH known movie library roots. It does
not create folders, infer genre from a movie title, or include TV episodes.
Each stage of sourcing must filter by the same scope.
"""
from pathlib import Path
import re

SCOPE = "horror-drama-folders"
ROOTS = (
    Path("/mnt/BigDisk/Video/Movies"),
    Path("/mnt/2TB/Plex Expansion/Movies"),
)
CATEGORIES = {"horror", "drama suspense", "drama", "suspense"}


def matches(row, scope="all"):
    if scope == "all":
        return True
    if scope != SCOPE:
        raise ValueError("unsupported_japanese_source_scope")
    if not isinstance(row, dict) or row.get("kind") != "Movie":
        return False
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
