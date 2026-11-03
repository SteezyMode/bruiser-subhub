#!/usr/bin/env python3
"""Fail-closed one-off recovery of Hy-MT2 7B full-SRT part 5.

English cue 147: "We have received an overwhelmingly positive response"
English cue 148: "to our Jim Brown sculpture idea."
English cue 149: "-Where's Douglas? / -He didn't show up today."

The raw result merged empty cue 148's header into cue 149's block.
If *both* clauses of 147+148 were translated in cue 147 and occupy exactly
two separate Japanese lines, move the second line into 148. Keep the two
dialogue lines of cue 149 TOGETHER in cue 149 (they form ONE original cue).

Never invent, retranslate, or overwrite Japanese text; preserve raw response;
verify all 30 source cue numbers, timestamps, and nonempty text before saving.
"""

import importlib.util
import re
from pathlib import Path

DIR = Path("/tmp/subhub-hy-mt2-full-chair-test")
ENGINE = Path("/tmp/subhub_hy_mt2_full_srt_test.py")


def main():
    if not ENGINE.is_file():
        raise RuntimeError(f"Existing engine not found: {ENGINE}")
    spec = importlib.util.spec_from_file_location("existing_hy_runner", ENGINE)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)

    original = m.parse_srt((DIR / "original.en.srt").read_text(encoding="utf-8"))
    expected = original[120:150]
    if [int(n) for n, _, _ in expected] != list(range(121, 151)):
        raise RuntimeError("English cue IDs 121-150 differ; stopping")
    src = {int(n): (t, txt) for n, t, txt in expected}
    if not (
        "overwhelmingly" in src[147][1]
        and "to our Jim Brown sculpture idea." in src[148][1]
        and "Where's Douglas?" in src[149][1]
        and "He didn't show up today." in src[149][1]
    ):
        raise RuntimeError("Original English dialog mapping differs; stopping")
    print("Verified: English 147 = response, 148 = sculpture, 149 = Douglas exchange.")

    raw_path = DIR / "part-0005.raw.txt"
    raw = raw_path.read_text(encoding="utf-8").replace("\r\n", "\n")
    parts = re.split(r"\n[ \t]*\n", raw.strip())
    ids = [re.findall(r"(?m)^(\d+)$", block) for block in parts]
    merged = [i for i, seq in enumerate(ids) if seq == ["148", "149"]]
    if len(parts) != 29 or len(merged) != 1:
        raise RuntimeError(f"Unexpected raw structure: blocks={len(parts)}, merged={merged}; no changes")
    at = merged[0]
    if at == 0 or ids[at - 1] != ["147"]:
        raise RuntimeError(f"Expected preceding block to be cue 147, got {ids[at-1] if at else None}")

    # Decode only the single otherwise valid 147 block.
    parsed_147 = m.parse_srt(parts[at - 1])
    if len(parsed_147) != 1 or parsed_147[0][:2] != ("147", src[147][0]):
        raise RuntimeError("Source 147 timestamp/header mismatch")
    original_147_lines = parsed_147[0][2].splitlines()
    if len(original_147_lines) != 2 or not all(x.strip() for x in original_147_lines):
        print("Cue 147 actual text:", repr(parsed_147[0][2]), flush=True)
        raise RuntimeError("Cannot safely split cue 147: it is not exactly two Japanese lines")
    ja147, ja148 = (x.strip() for x in original_147_lines)
    if not (re.search(r"[\u3040-\u30ff\u4e00-\u9fff]", ja147) and
            re.search(r"[\u3040-\u30ff\u4e00-\u9fff]", ja148)):
        raise RuntimeError("Cue 147 did not contain two Japanese text lines")
    print("Existing 147 Japanese line 1:", ja147, flush=True)
    print("Existing 147 Japanese line 2:", ja148, flush=True)

    # The malformed raw block has two headers followed by TWO speech lines,
    # both of which belong in original English cue 149.
    pair = parts[at].splitlines()
    if len(pair) != 6 or pair[:4] != ["148", src[148][0], "149", src[149][0]]:
        raise RuntimeError(f"Unexpected 148/149 merged block: {pair!r}")
    ja149 = [x.strip() for x in pair[4:]]
    if not all(s.startswith("-") for s in ja149):
        raise RuntimeError(f"149 did not contain the expected two dialogue lines: {ja149!r}")
    if not all(re.search(r"[\u3040-\u30ff\u4e00-\u9fff]", s) for s in ja149):
        raise RuntimeError("Cue 149 Japanese lines not present")
    print("Existing 149 Japanese lines:", repr(ja149), flush=True)

    parts[at - 1] = f"147\n{src[147][0]}\n{ja147}"
    parts[at] = (
        f"148\n{src[148][0]}\n{ja148}\n\n"
        f"149\n{src[149][0]}\n" + "\n".join(ja149)
    )
    fixed = "\n\n".join(parts) + "\n"
    validated = m.compare_structure(expected, fixed)
    if len(validated) != 30:
        raise RuntimeError("Unexpected verified result length")

    target = DIR / "part-0005.ja.srt"
    validated_srt = m.as_srt(validated)
    if target.is_file():
        if target.read_text(encoding="utf-8") != validated_srt:
            raise RuntimeError("An existing verified part 5 differs; refusing overwrite")
        print("Part 5 already verified; nothing rewritten")
        return
    m.new_text(target, validated_srt)
    (DIR / "part-0005.recovery-note.txt").write_text(
        "The untouched model reply is part-0005.raw.txt.\n"
        "English 147 spans overwhelming response; English 148 is Jim Brown sculpture;\n"
        "English 149 is Douglas dialogue (both speaker lines in ONE cue).\n"
        "The model put both Japanese response clauses in cue 147 and no text in cue 148.\n"
        "Moved the SECOND existing Japanese line from 147 to 148.\n"
        "Separated 148 and 149 headers, retaining both speaker lines under 149.\n"
        "NO Japanese rewritten, generated, or dropped.\n"
        "Exact 30 source cue numbers/timestamps verified.\n",
        encoding="utf-8"
    )
    print("PART 5 RECOVERED: 30/30 original IDs/timestamps; no new model call.")
    print("Original part-0005.raw.txt preserved, source media untouched.")


if __name__ == "__main__":
    main()
