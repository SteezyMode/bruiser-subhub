#!/usr/bin/env python3
"""Jellyfin-authoritative, Japanese-first library intake manifest.

Runs on the OptiPlex HOST, not inside Sublarr. Reads Jellyfin metadata,
Docker's existing Sublarr bind mounts and local sidecar filenames. It does
NOT contact subtitle providers, scan media bytes, run ffprobe, download,
translate, modify Jellyfin/Sublarr, or write anything unless --save is set.

A queue item is NOT permission to download or publish: later acquisition
must enforce identity, language, release and existing-subtitle checks again.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import urlencode
from urllib.request import Request, urlopen

AUTH = Path.home() / ".config/bruiser/jellyfin-english-source-auth.json"
STATE = Path.home() / "bruiser-pilot/ja-first-inventory"
BASE = "http://127.0.0.1:8096"
PAGE = 200
MAX_PAGES = 150
ALLOWED_MOUNTS = (
    "/media/bigdisk-video",
    "/media/expansion-video",
    "/media/american-dad-main",
    "/media/american-dad-2tb",
)
SUB_EXT = {".srt", ".ass", ".ssa", ".vtt"}
VIDEO_EXT = {".mp4", ".mkv", ".avi", ".m4v", ".wmv", ".webm", ".ts", ".mov", ".mpg", ".mpeg", ".m2ts"}
IMDB = re.compile(r"tt\d{5,12}\Z", re.I)
JELLYFIN_ID = re.compile(r"[0-9a-fA-F]{32}\Z")
CLEAN_TAG = re.compile(r"[^a-z0-9]+")
UNKNOWN_AUDIO = {"", "und", "unknown", "mul", "zxx", "none"}
COUNTS = ("existing_japanese_subtitle", "japanese_audio", "ready_ja_search",
          "review_audio_language_unverified", "review_no_movie_imdb", "review_missing_series_identity",
          "review_missing_episode_number", "review_missing_media_streams",
          "review_missing_path", "review_unmapped_path", "review_host_file_missing")


def lang(value):
    return str(value or "").lower().replace("_", "-").split("-")[0].strip()


def is_ja(value):
    return lang(value) in {"ja", "jp", "jpn", "japanese"}


def is_forced(entry):
    if entry.get("IsForced") is True:
        return True
    desc = " ".join(str(entry.get(k) or "") for k in ("Title", "DisplayTitle"))
    return bool(re.search(r"\b(?:forced|signs.?only)\b", desc, re.I))


def names_to_check(path, cache):
    parent = path.parent
    if parent not in cache:
        try:
            cache[parent] = tuple(p.name for p in parent.iterdir() if p.is_file() and not p.is_symlink())
        except OSError:
            cache[parent] = ()
    return cache[parent]


def sidecar_ja(path, cache):
    """Only a specifically language-tagged, unforced sidecar for this release."""
    prefix = path.stem.casefold() + "."
    for name in names_to_check(path, cache):
        other = Path(name)
        if other.suffix.casefold() not in SUB_EXT:
            continue
        if not name.casefold().startswith(prefix):
            continue
        suffix = name[len(prefix):-len(other.suffix)]
        tokens = [t for t in CLEAN_TAG.split(suffix.casefold()) if t]
        if any(is_ja(token) for token in tokens) and "forced" not in tokens and "signs" not in tokens:
            return True
    return False


def streams_for(item):
    streams = item.get("MediaStreams")
    if isinstance(streams, list):
        return streams
    sources = item.get("MediaSources")
    if isinstance(sources, list):
        for source in sources:
            if isinstance(source, dict) and isinstance(source.get("MediaStreams"), list):
                return source["MediaStreams"]
    return None


def stream_state(item):
    streams = streams_for(item)
    if streams is None:
        return "unknown", "unknown", False
    ja_sub = any(
        s.get("Type") == "Subtitle" and is_ja(s.get("Language")) and not is_forced(s)
        for s in streams if isinstance(s, dict)
    )
    audio = [s for s in streams if isinstance(s, dict) and s.get("Type") == "Audio"]
    primary = next((s for s in audio if s.get("IsDefault") is True), audio[0] if audio else {})
    primary_lang = lang(primary.get("Language")) or "unknown"
    return "known", primary_lang, ja_sub


def load_auth():
    if not AUTH.is_file() or AUTH.is_symlink() or AUTH.stat().st_mode & 0o077:
        raise RuntimeError("Missing or unsafe private Jellyfin auth file")
    auth = json.loads(AUTH.read_text())
    if not isinstance(auth.get("token"), str) or not isinstance(auth.get("device_id"), str):
        raise RuntimeError("Malformed Jellyfin auth file")
    return (
        'MediaBrowser Client="Bruiser JA Intake", '
        'Device="OptiPlex", DeviceId="' + auth["device_id"] + '", '
        'Version="1.0", Token="' + auth["token"] + '"'
    )


def load_mounts():
    raw = subprocess.check_output(
        ["docker", "inspect", "-f", "{{json .Mounts}}", "sublarr-pilot"],
        text=True, timeout=15
    )
    mounts = json.loads(raw)
    result = []
    for m in mounts:
        if m.get("Type") != "bind" or m.get("Destination") not in ALLOWED_MOUNTS:
            continue
        source = Path(m["Source"])
        if source.is_dir() and not source.is_symlink():
            result.append((source, Path(m["Destination"])))
    if not result:
        raise RuntimeError("No approved Sublarr library bind mounts found")
    return sorted(result, key=lambda pair: len(pair[0].parts), reverse=True)


def map_path(path, mounts):
    if not isinstance(path, str) or not path.startswith("/"):
        return None
    host = Path(path)
    for root, destination in mounts:
        if host.is_relative_to(root):
            return str(destination / host.relative_to(root))
    return None


def page_items(header, kind):
    for page in range(MAX_PAGES):
        query = urlencode({
            "Recursive": "true", "IncludeItemTypes": kind,
            "Fields": "Path,ProviderIds,MediaStreams,MediaSources,Studios,ProductionLocations,OriginalTitle",
            "StartIndex": page * PAGE, "Limit": PAGE,
        })
        req = Request(BASE + "/Items?" + query, headers={"Authorization": header})
        with urlopen(req, timeout=40) as response:
            result = json.load(response)
        items = result.get("Items")
        if not isinstance(items, list):
            raise RuntimeError("Invalid Jellyfin catalog response")
        yield from items
        count = result.get("TotalRecordCount")
        if len(items) < PAGE or (type(count) is int and (page + 1) * PAGE >= count):
            return
    raise RuntimeError("Catalog pagination exceeded safety limit")


def provider_ids(item):
    return {str(k).casefold(): str(v).strip()
            for k, v in (item.get("ProviderIds") or {}).items() if v}


def classify(item, series, mounts, sidecache):
    kind = item.get("Type")
    data = {
        "jellyfin_id": item.get("Id"), "kind": kind,
        "title": item.get("Name") or "",
        # Jellyfin's own authoritative original title (e.g. 恋の罪).
        # This is a SECOND independent title alias, never user-provided
        # release text or an automatically trusted provider ID.
        "original_title": str(item.get("OriginalTitle") or "")[:240]
            if kind == "Movie" else "",
        "host_path": item.get("Path") or "",
        "sublarr_path": None, "status": None, "audio_language": "unknown",
        "imdb_id": "", "tmdb_id": "", "series_title": "",
        "series_imdb_id": "", "series_tmdb_id": "", "series_tvdb_id": "",
        "series_jellyfin_id": "", "series_identity_source": "",
        "season": None, "episode": None, "year": item.get("ProductionYear"),
        "genres": [str(v) for v in (item.get("Genres") or [])[:20]
                   if isinstance(v, str)][:20],
        # Keep animation origin metadata for the shared anime exclusion.
        # A Japanese dub or an Animation genre alone does not mean anime.
        "production_locations": [
            str(v)[:100] for v in (item.get("ProductionLocations") or [])[:20]
            if isinstance(v, str)],
        "studios": [
            str(v.get("Name") or "")[:100] for v in
            (item.get("Studios") or [])[:20] if isinstance(v, dict)],
    }
    # Populate series/season identity before the coverage short circuit.
    # Previously every already-subtitled TV episode returned with an empty
    # series_title and missing S/E, obscuring series-wide coverage audits.
    # This is descriptive metadata only: no change to search eligibility.
    if kind == "Episode":
        data["season"] = item.get("ParentIndexNumber")
        data["episode"] = item.get("IndexNumber")
        parent = series.get(item.get("SeriesId"))
        data["series_title"] = (
            str((parent or {}).get("Name") or "").strip()
            or str(item.get("SeriesName") or "").strip()
        )
        # Jellyfin usually categorizes *series*, not each episode. Carry
        # those actual Jellyfin genres into the episode inventory so the
        # browser's Documentary/Comedy/etc. collections are complete.
        existing={g.casefold() for g in data["genres"]}
        for genre in (parent or {}).get("Genres") or []:
            if (isinstance(genre,str) and 1<=len(genre)<=60 and
                    genre.casefold() not in existing and len(data["genres"])<20):
                data["genres"].append(genre)
                existing.add(genre.casefold())

    path = data["host_path"]
    if not path:
        data["status"] = "review_missing_path"
        return data
    mapped = map_path(path, mounts)
    if mapped is None:
        data["status"] = "review_unmapped_path"
        return data
    data["sublarr_path"] = mapped
    host = Path(path)
    if host.suffix.casefold() not in VIDEO_EXT or host.is_symlink() or not host.is_file():
        data["status"] = "review_host_file_missing"
        return data
    # A bind mount can contain linked subfolders; never trust a lexical prefix alone.
    if not any(
        host.resolve().is_relative_to(root.resolve()) for root, _ in mounts
    ):
        data["status"] = "review_unmapped_path"
        return data

    info_state, audio_lang, embedded_ja = stream_state(item)
    data["audio_language"] = audio_lang
    if sidecar_ja(host, sidecache) or embedded_ja:
        data["status"] = "existing_japanese_subtitle"
        return data
    if is_ja(audio_lang):
        data["status"] = "japanese_audio"
        return data

    if kind == "Movie":
        ids = provider_ids(item)
        data["imdb_id"] = ids.get("imdb", "")
        data["tmdb_id"] = ids.get("tmdb", "")
        # IMDb helps discovery, but missing IMDb must not hide a film from
        # title+year Japanese subtitle searches. Publication still checks
        # candidate file identity, year, and existing media tracks.
        if not IMDB.fullmatch(data["imdb_id"]):
            data["imdb_id"] = ""
    elif kind == "Episode":
        data["season"] = item.get("ParentIndexNumber")
        data["episode"] = item.get("IndexNumber")
        if not (type(data["season"]) is int and data["season"] >= 1
                and type(data["episode"]) is int and data["episode"] >= 1):
            data["status"] = "review_missing_episode_number"
            return data
        raw_series_id = item.get("SeriesId")
        parent = series.get(raw_series_id)
        ids = provider_ids(parent) if parent else {}
        parent_title = str((parent or {}).get("Name") or "").strip()
        episode_series_title = str(item.get("SeriesName") or "").strip()
        data["series_title"] = parent_title or episode_series_title
        data["series_imdb_id"] = ids.get("imdb", "")
        data["series_tmdb_id"] = ids.get("tmdb", "")
        data["series_tvdb_id"] = ids.get("tvdb", "")
        provider_identity = any((
            data["series_imdb_id"], data["series_tmdb_id"],
            data["series_tvdb_id"]))
        # Jellyfin itself knows the episode's parent series ID and name, even
        # when third-party IMDb/TMDb/TVDb IDs have never been scraped. Use that
        # native identity for *search eligibility* only; downstream staging
        # still demands independent exact-series/season/episode evidence.
        native_identity = (
            isinstance(raw_series_id, str)
            and bool(JELLYFIN_ID.fullmatch(raw_series_id))
            and bool(data["series_title"])
            and (parent is None or str(parent.get("Id") or "") == raw_series_id)
            and (not parent_title or not episode_series_title
                 or CLEAN_TAG.sub("",parent_title.casefold()) ==
                    CLEAN_TAG.sub("",episode_series_title.casefold()))
            and (parent is not None or bool(episode_series_title))
        )
        if native_identity:
            data["series_jellyfin_id"] = raw_series_id
        if not data["series_title"] or not (provider_identity or native_identity):
            data["status"] = "review_missing_series_identity"
            return data
        data["series_identity_source"] = (
            "provider" if provider_identity else "jellyfin")
    else:
        data["status"] = "review_missing_series_identity"
        return data

    # Absent stream lists cannot establish whether JA was already embedded.
    # Hold these items instead of creating a misleading search-ready queue.
    if info_state != "known":
        data["status"] = "review_missing_media_streams"
    elif audio_lang in UNKNOWN_AUDIO:
        # Unknown audio tags are not missing episode identity. Safe to
        # DISCOVER subtitle candidates without inferring spoken language.
        # Audio unknown stays explicit; embedded JA and exact-file sidecars
        # have already been checked. No existing media is replaced.
        data["audio_review_required"] = True
        data["status"] = "ready_ja_search"
    else:
        data["status"] = "ready_ja_search"
    return data


def self_test():
    assert is_ja("ja-JP") and is_ja("jpn") and not is_ja("en")
    p = Path("/mnt/Movies/Friday.1995.mkv")
    mounts = [(Path("/mnt/Movies"), Path("/media/movies")),
              (Path("/mnt"), Path("/media/root"))]
    assert map_path(str(p), mounts) == "/media/movies/Friday.1995.mkv"
    assert map_path("/unrelated/file.mkv", mounts) is None
    cache = {p.parent: ("Friday.1995.ja.srt", "Friday.1995.ja.forced.srt")}
    assert sidecar_ja(p, cache)
    cache[p.parent] = ("Friday.1995.ja.forced.srt", "Other.Movie.ja.srt")
    assert not sidecar_ja(p, cache)
    assert stream_state({"MediaStreams": [
        {"Type": "Audio", "Language": "eng", "IsDefault": True},
        {"Type": "Subtitle", "Language": "jpn", "IsForced": True}
    ]}) == ("known", "eng", False)
    assert stream_state({"MediaStreams": [
        {"Type": "Subtitle", "Language": "ja-JP", "IsForced": False}
    ]})[2] is True
    assert lang("und") in UNKNOWN_AUDIO and lang("jpn") not in UNKNOWN_AUDIO
    print("SELF-TEST PASSED (no network or writes)")


def save_manifest(result):
    STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    if STATE.is_symlink() or STATE.stat().st_mode & 0o077:
        raise RuntimeError("Unsafe private manifest state directory permissions")
    filename = "ja-intake-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + ".json"
    path = STATE / filename
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print("PRIVATE MANIFEST:", path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--save", action="store_true",
                        help="write a new private JSON catalog (0600), never overwrite")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return
    header = load_auth()
    mounts = load_mounts()
    print("=== JAPANESE-FIRST LIBRARY INTAKE ===", flush=True)
    print("Host/Jellyfin paths mapped to Sublarr binds:", len(mounts), flush=True)
    series = {s["Id"]: s for s in page_items(header, "Series") if s.get("Id")}
    counts = Counter()
    sidecache = {}
    entries = []
    seen = set()
    for item in page_items(header, "Movie,Episode"):
        if item.get("Type") not in ("Movie", "Episode"):
            continue
        if not item.get("Id") or item["Id"] in seen:
            counts["duplicate_or_missing_jellyfin_id"] += 1
            continue
        seen.add(item["Id"])
        row = classify(item, series, mounts, sidecache)
        counts[row["status"]] += 1
        entries.append(row)
        if len(entries) % 2000 == 0:
            print("Processed", len(entries), "Jellyfin items...", flush=True)

    print("\n=== CLASSIFICATION ===")
    for status in COUNTS:
        print(f"{status}: {counts.get(status, 0)}")
    for status, total in sorted(counts.items()):
        if status not in COUNTS:
            print(f"{status}: {total}")
    print("total_unique_items:", len(entries))
    print("series_registered:", len(series))
    print("ready_movies:", sum(1 for e in entries
                               if e["status"] == "ready_ja_search" and e["kind"] == "Movie"))
    print("ready_episodes:", sum(1 for e in entries
                                 if e["status"] == "ready_ja_search" and e["kind"] == "Episode"))

    examples = defaultdict(list)
    for e in entries:
        if e["status"].startswith("review_") and len(examples[e["status"]]) < 2:
            examples[e["status"]].append(e["title"])
    print("\n=== REVIEW EXAMPLES ===")
    for key, titles in sorted(examples.items()):
        print(key, json.dumps(titles, ensure_ascii=False))

    if args.save:
        save_manifest({
            "schema": 1, "generated_utc": datetime.now(timezone.utc).isoformat(),
            "source": "Jellyfin+Sublarr bind mounts", "counts": dict(counts),
            "items": entries,
        })
    print("\nDONE: No provider searches, downloads, model work, media or service modifications.")
    if not args.save:
        print("No files written; use --save for a private, non-overwriting manifest.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # Never echo authentication headers, tokens or provider query URLs.
        print("INTAKE ERROR:", type(exc).__name__, str(exc)[:160], file=sys.stderr)
        raise SystemExit(1) from None
