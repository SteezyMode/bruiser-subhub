#!/usr/bin/env python3
"""Recover the known Hy-MT2 cue 148/149 merge, WITHOUT changing its Japanese.

One-off, fail-closed repair of the already saved response:
  148 <timestamp> 149 <timestamp> <Japanese line for 148> <Japanese line for 149>
Only acts on original part-0005.raw.txt, verifies all 30 source IDs/times against
the original source, and creates part-0005.ja.srt. Never edits raw or media.
"""
import importlib.util
import re
from pathlib import Path

DIR = Path("/tmp/subhub-hy-mt2-full-chair-test")
ENGINE = Path("/tmp/subhub_hy_mt2_full_srt_test.py")

def main():
    if not ENGINE.is_file():
        raise RuntimeError(f"Existing translation engine not found: {ENGINE}")
    spec = importlib.util.spec_from_file_location("hy_existing", ENGINE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    original = module.parse_srt((DIR / "original.en.srt").read_text(encoding="utf-8"))
    expected = original[120:150]
    if [int(item[0]) for item in expected] != list(range(121, 151)):
        raise RuntimeError("English IDs 121-150 not as expected")

    lookup = {int(n): (t, txt) for n, t, txt in expected}
    if "Where's Douglas?" not in lookup[148][1] or "He didn't show up today." not in lookup[149][1]:
        raise RuntimeError("Source dialogue differs; refusing ambiguous repair")
    raw_file = DIR / "part-0005.raw.txt"
    raw = raw_file.read_text(encoding="utf-8")
    raw_blocks = re.split(r"\n[ \t]*\n", raw.replace("\r\n", "\n").strip())
    hits = [i for i,b in enumerate(raw_blocks) if b.startswith("148\n")]
    if len(hits) != 1:
        raise RuntimeError(f"Expected one merged block starting with 148; found {len(hits)}")
    index = hits[0]
    lines = raw_blocks[index].strip().splitlines()
    if len(lines) != 6 or lines[0] != "148" or lines[2] != "149":
        raise RuntimeError(f"Unexpected merged block layout; no repair: {lines!r}")
    if lines[1] != lookup[148][0] or lines[3] != lookup[149][0]:
        raise RuntimeError("Cue timestamps disagree with original English SRT")
    ja148, ja149 = lines[4].strip(), lines[5].strip()
    if (not ja148.startswith("-") or not ja149.startswith("-")
        or not re.search(r"[\u3040-\u30ff\u4e00-\u9fff]", ja148)
        or not re.search(r"[\u3040-\u30ff\u4e00-\u9fff]", ja149)):
        raise RuntimeError(f"Expected two Japanese dialogue lines, got: {ja148!r}, {ja149!r}")

    raw_blocks[index] = (
        f"148\n{lookup[148][0]}\n{ja148}\n\n"
        f"149\n{lookup[149][0]}\n{ja149}"
    )
    repaired = "\n\n".join(raw_blocks) + "\n"
    parsed = module.compare_structure(expected, repaired)
    verified_path = DIR / "part-0005.ja.srt"
    if verified_path.exists():
        existing = verified_path.read_text(encoding="utf-8")
        if existing != module.as_srt(parsed):
            raise RuntimeError(f"Different verified output already exists: {verified_path}")
        print("Part 5 was already repaired and verified; no changes.")
        return
    # Preserve untouched raw, creating a separate validated and transparently
    # documented output file. No model call or Japanese changes.
    module.new_text(verified_path, module.as_srt(parsed))
    note = (
        "Manual mechanical split of merged indices 148 and 149.\n"
        "English source verified: 148 Where's Douglas? / 149 He didn't show up today.\n"
        f"Japanese 148 verbatim: {ja148}\nJapanese 149 verbatim: {ja149}\n"
        f"Unchanged model response retained: {raw_file}\n"
    )
    (DIR / "part-0005.recovery-note.txt").write_text(note, encoding="utf-8")
    print("RECOVERED: part 5, all 30 cue IDs/timestamps validated; original Japanese unchanged.")
    print("Cue 148:", ja148)
    print("Cue 149:", ja149)
    print("Original raw response preserved. Resuming is safe.")

if __name__ == "__main__":
    main()
