"""Exact movie-folder scope for owner-selected Japanese subtitle sourcing.

Scope matches existing folders under BOTH known movie library roots. It does
not create folders, infer genre from a movie title, or include TV episodes.
Each stage of sourcing must filter by the same scope.
"""
from pathlib import Path
import re
try:
    from . import subhub_media_categories as categories
except ImportError:
    import subhub_media_categories as categories

SCOPE = "horror-drama-folders"
MOVIES_NO_ANIME = "movies-no-anime"
MOVIES_ALL = "movies-all"
MOVIES_DRAMA = "movies-drama"
MOVIES_HORROR = "movies-horror"
MOVIES_ACTION = "movies-action"
GENRE_SCOPES = {
    MOVIES_DRAMA: {"drama", "suspense", "thriller"},
    MOVIES_HORROR: {"horror"},
    MOVIES_ACTION: {"action"},
}
SCOPES = ("all", SCOPE, MOVIES_NO_ANIME, MOVIES_ALL, *GENRE_SCOPES)
ROOTS = (
    Path("/mnt/BigDisk/Video/Movies"),
    Path("/mnt/2TB/Plex Expansion/Movies"),
)
CATEGORIES = {"horror", "drama suspense", "drama", "suspense"}

# Default source jobs cover every episode and non-anime film. An explicit
# movies-all scope remains available for an owner who wants anime included.
# Check authoritative Jellyfin metadata and directory categories, not a
# hard-coded movie-title blacklist. In particular, "Animation" alone is
# insufficient: Western animated movies remain eligible.
JAPANESE_ANIMATION_STUDIOS = (
    "studio ghibli", "toei animation", "kyoto animation",
    "madhouse", "production i.g", "wit studio", "studio trigger",
    "a-1 pictures", "ufotable", "studio bones",
)


def is_anime_movie(row):
    if not isinstance(row, dict) or row.get("kind") != "Movie":
        return False
    genres = row.get("genres") or []
    labels = {word for g in genres if isinstance(g, str)
              for word in re.findall(r"[a-z]+", g.casefold())}
    if "anime" in labels:
        return True
    value = row.get("host_path")
    if isinstance(value, str) and value.startswith("/"):
        path = Path(value)
        for root in ROOTS:
            try:
                parts = path.relative_to(root).parts[:-1]
            except ValueError:
                continue
            if any(re.search(r"(?i)(?<![a-z])anime", part) for part in parts):
                return True
    if "animation" not in labels and "animated" not in labels:
        return False
    # OriginalTitle is Japanese for many anime even when the media has
    # an English dub. This does not exclude Japanese live-action films.
    original = str(row.get("original_title") or "")
    if re.search(r"[\u3040-\u30ff\u3400-\u9fff]", original):
        return True
    places = row.get("production_locations") or []
    if any(isinstance(place, str) and place.strip().casefold() in
           {"japan", "日本"} for place in places):
        return True
    studios = " ".join(str(studio).casefold()
                       for studio in row.get("studios") or [])
    return any(studio in studios for studio in JAPANESE_ANIMATION_STUDIOS)


def matches(row, scope="all"):
    if scope not in SCOPES:
        raise ValueError("unsupported_japanese_source_scope")
    if scope == "all":
        return not is_anime_movie(row)
    if not isinstance(row, dict) or row.get("kind") != "Movie":
        return False
    if scope != MOVIES_ALL and is_anime_movie(row):
        return False
    if scope in GENRE_SCOPES:
        # Both actual movie libraries, never an episode, synthetic title
        # classification, or a path outside the configured movie mounts.
        value = row.get("host_path")
        if not isinstance(value, str) or not value.startswith("/"):
            return False
        path = Path(value)
        if path.is_symlink() or ".." in path.parts:
            return False
        sections = []
        for root in ROOTS:
            try:
                rel = path.relative_to(root)
            except ValueError:
                continue
            if len(rel.parts) < 2:
                return False
            sections.append(rel.parts[0])
        if not sections:
            return False
        # A Jellyfin genre is authoritative. The first actual library
        # folder supplements missing genre metadata (e.g. "Drama, Suspense").
        # Never infer genre from a film title, release group or nested folders.
        labels = list(row.get("genres") or []) + sections
        words = {token for label in labels if isinstance(label, str)
                 for token in re.findall(r"[a-z]+", label.casefold())}
        return bool(words & GENRE_SCOPES[scope])
    if scope == MOVIES_ALL:
        # Every Jellyfin Movie physically within either configured movie root,
        # including anime and animation. Never mix in Television or unsafe
        # paths: this scope is for owner-initiated movie library sweeps.
        value = row.get("host_path")
        if not isinstance(value, str) or not value.startswith("/"):
            return False
        path = Path(value)
        if path.is_symlink() or ".." in path.parts:
            return False
        return any(path != root and path.is_relative_to(root) for root in ROOTS)
    if scope == MOVIES_NO_ANIME:
        # Only approved movie roots; anime was excluded above for all
        # ordinary scopes. An explicit movies-all is the sole opt-in.
        value = row.get("host_path")
        if not isinstance(value, str) or not value.startswith("/"):
            return False
        path = Path(value)
        if path.is_symlink() or ".." in path.parts:
            return False
        return any(path != root and path.is_relative_to(root)
                   for root in ROOTS)
    value = row.get("host_path")
    if not isinstance(value, str) or not value.startswith("/"):
        return False
    path = Path(value)
    if path.is_symlink():
        return False
    # Match the same *real Jellyfin categories* shown in the browser,
    # rather than only names under one hardcoded movie folder. All later
    # staging/publication still enforce actual approved host mount paths.
    labels={label.casefold() for label in categories.categories(
        "Movie",value,row.get("genres") or [])}
    if labels & {"horror","drama"}:
        return True
    for root in ROOTS:
        try:
            relative = path.relative_to(root)
        except ValueError:
            continue
        if len(relative.parts) < 2:
            return False
        category = re.sub(r"[^a-z]+", " ", relative.parts[0].casefold()).strip()
        return category in CATEGORIES
    return False


def select(rows, scope="all"):
    return [r for r in rows if matches(r, scope)]
