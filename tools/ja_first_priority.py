"""Search/staging priorities for the household's existing Japanese subtitles.

Avoid brittle hard-coded filesystem paths: prefer Jellyfin Genres when present,
but also recognize movie folders named Horror, Drama, Suspense or Thriller.
Keep all other media eligible for later passes. No user-level private data here.
"""
from __future__ import annotations

import re
from pathlib import Path
import sqlite3

QUEUE_DB = Path.home() / "bruiser-pilot/coverage-queue/coverage.sqlite3"


def active_coverage_queue(path=QUEUE_DB):
    """Read installed Bruiser queue, never create a DB or change task states.

    Return None only when the queue has not been initialized. An unexpected
    installed schema or unsafe permissions is a hard stop, not a fallback to
    quota-inefficient old source selection.
    """
    path = Path(path)
    if not path.exists() and not path.is_symlink():
        return None
    if (path.is_symlink() or not path.is_file() or path.stat().st_mode & 0o077
            or path.parent.is_symlink() or path.parent.stat().st_mode & 0o077):
        raise RuntimeError("Unsafe installed Bruiser coverage queue")
    with sqlite3.connect("file:" + str(path.resolve()) + "?mode=ro",
                         uri=True, timeout=15) as db:
        rows = db.execute("""
            SELECT m.jellyfin_id, t.action, t.state, t.priority, m.path
            FROM tasks AS t JOIN media AS m ON m.path = t.path
            WHERE t.active=1 AND t.target='ja'
        """).fetchall()
    result = {}
    for jid, action, state, priority, pathstr in rows:
        key = str(jid)
        if key in result:
            raise RuntimeError("Multiple JA tasks for same Jellyfin identity")
        result[key] = (str(action), str(state), int(priority), str(pathstr))
    return result


def queue_position(row, action, tasks):
    """Return queue priority for action, None for deferred/unready rows.

    Newly added media absent from a stale snapshot may still receive a new
    provider search, but AFTER eligible known pending items.
    """
    jid = str(row.get("jellyfin_id") or "")
    if tasks is None:
        return (100, priority(row))
    known = tasks.get(jid)
    if known is None:
        return (300, priority(row))
    queued_action, state, rank, path = known
    if state != "pending":
        return None
    if str(row.get("host_path") or "") != path:
        return None
    if action == "search":
        # Older queue snapshots incorrectly marked one zero-result search as
        # an English->Japanese translation fallback. This was NOT exhausted
        # sourcing. Restore discoverability immediately without a queue reset.
        source_actions={"search_ja","validate_english_for_ja_fallback",
                        "recover_english_for_ja_fallback"}
        return (rank, priority(row)) if queued_action in source_actions else None
    if action == "stage":
        # A newly recovered subtitle should stage in this SAME run even if
        # the old queue still labels the title as an English fallback.
        if queued_action in ("download_saved_ja", "search_ja",
                             "validate_english_for_ja_fallback",
                             "recover_english_for_ja_fallback"):
            return (rank if queued_action == "download_saved_ja"
                    else 200, priority(row))
        return None
    raise ValueError("Unknown coverage queue action")



# No hard-coded show priority: every series participates in the same queue.


def simplify(text):
    return re.sub(r"[^a-z0-9]+", "", str(text or "").casefold())


def priority(row):
    kind = row.get("kind")
    if kind == "Episode":
        return 2
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
