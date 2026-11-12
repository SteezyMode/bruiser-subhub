"""One read-only virtual category name per Jellyfin genre across all media roots.

Both the host source worker and the dashboard import this exact helper.
No symlinks, media moves, or provider requests.
"""
from pathlib import PurePosixPath
import re

ALIASES={
    "documentaries":"Documentary",
    "documentary films":"Documentary",
    "documentary series":"Documentary",
    "action & adventure":"Action",
    "action and adventure":"Action",
    "sci-fi":"Science Fiction",
    "sci fi":"Science Fiction",
    "science-fiction":"Science Fiction",
}
FOLDERS={
    "action","adventure","animation","anime","comedy","crime","documentary",
    "drama","family","fantasy","history","horror","kids","music",
    "musical","mystery","reality","romance","science fiction","sci-fi",
    "sport","suspense","thriller","war","western","classics",
}


def normalize(text):
    if not isinstance(text,str):
        return ""
    label=" ".join(text.strip().split())
    if not label or len(label)>120 or any(ord(ch)<32 for ch in label):
        return ""
    return ALIASES.get(label.casefold(),label)


def physical_movie_category(path):
    try:
        parts=PurePosixPath(path).parts
    except (TypeError,ValueError):
        return ""
    matches=[i for i,p in enumerate(parts[:-1])
             if p.casefold() in ("movies","films","film")]
    if not matches:
        return ""
    components=parts[min(matches)+1:-1]
    if not components:
        return ""
    label=normalize(components[0])
    return label if label.casefold() in FOLDERS or label in ALIASES.values() else ""


def categories(kind,path,genres):
    """Genre collections; use a real, recognizable disk genre as a supplement."""
    found={}
    for raw in genres or []:
        label=normalize(raw)
        if label:
            found.setdefault(label.casefold(),label)
    if kind=="Movie":
        physical=physical_movie_category(path)
        if physical:
            found.setdefault(physical.casefold(),physical)
    elif kind=="Episode":
        # TV episodes may lack genres, but Documentary folders are meaningful.
        # Never infer a genre from a series name or arbitrary release directory.
        try:
            segments=PurePosixPath(path).parts[:-1]
        except (TypeError,ValueError):
            segments=()
        if any(str(part).casefold() in
               ("documentary","documentaries","documentary series")
               for part in segments):
            found.setdefault("documentary","Documentary")
    if not found:
        return ["Other Movies" if kind=="Movie" else "Other Television"]
    return sorted(found.values(),key=str.casefold)
