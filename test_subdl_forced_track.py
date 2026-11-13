"""Regression for Japanese dialogue SRT beside forced-only ZIP track."""
from io import BytesIO
import unittest
import zipfile

from tools import ja_first_stage_subdl as subdl


def build_zip(files):
    output = BytesIO()
    with zipfile.ZipFile(output, "w") as z:
        for name, body in files.items():
            z.writestr(name, body)
    return output.getvalue()


def full_japanese():
    blocks = []
    for i in range(100):
        start = i * 5
        a = f"00:{start//60:02}:{start%60:02},000"
        b = f"00:{(start+2)//60:02}:{(start+2)%60:02},000"
        blocks.append(f"{i+1}\n{a} --> {b}\n日本語の字幕です。\n")
    return "\n".join(blocks).encode("utf-8")


def film(title, year):
    return {"kind": "Movie", "title": title, "year": year}


class SubdlForcedTrackTests(unittest.TestCase):
    def test_full_japanese_plus_forced_is_one_unambiguous_track(self):
        normal = full_japanese()
        archive = build_zip({
            "Black Christmas (Japanese).srt": normal,
            "Black Christmas (Japanese Forced).srt": b"1\n00:00:01,000 --> 00:00:02,000\nsign\n",
        })
        data, qa, member = subdl.archive_srt(
            archive, film("Black Christmas", 1974), {}, 1200)
        self.assertEqual(member, "Black Christmas (Japanese).srt")
        self.assertEqual(data, normal)
        self.assertEqual(qa["cues"], 100)

    def test_short_title_plus_forced(self):
        archive = build_zip({
            "Prey (Japanese).srt": full_japanese(),
            "Prey (Japanese Forced).srt": b"short",
        })
        _, qa, member = subdl.archive_srt(
            archive, film("Prey", 2022), {}, 1200)
        self.assertEqual(member, "Prey (Japanese).srt")
        self.assertEqual(qa["cues"], 100)

    def test_explicit_conflicting_year_never_accepted(self):
        archive = build_zip({
            "Prey.2007.Japanese.srt": full_japanese(),
            "Prey.2007.Forced.srt": b"forced",
        })
        with self.assertRaisesRegex(RuntimeError,
                                    "subdl_archive_no_matching_srt_member"):
            subdl.archive_srt(archive, film("Prey", 2022), {}, 1200)

    def test_multiple_distinct_yearless_nonforced_versions_still_held(self):
        archive = build_zip({
            "Prey Japanese.srt": full_japanese(),
            "Prey Japanese alternative.srt": full_japanese(),
        })
        with self.assertRaisesRegex(RuntimeError,
                                    "subdl_archive_no_matching_srt_member"):
            subdl.archive_srt(archive, film("Prey", 2022), {}, 1200)

    def test_forced_only_never_accepted(self):
        archive = build_zip({
            "Prey (Japanese Forced).srt": full_japanese(),
        })
        with self.assertRaisesRegex(RuntimeError,
                                    "subdl_archive_only_forced_srt_members"):
            subdl.archive_srt(archive, film("Prey", 2022), {}, 1200)

    def test_rejected_content_still_rejected(self):
        archive = build_zip({
            "Prey (Japanese).srt": full_japanese().replace(
                "日本語の字幕です。".encode("utf-8"), b"English only")
        })
        with self.assertRaisesRegex(RuntimeError,
                                    "subdl_archive_srt_rejected"):
            subdl.archive_srt(archive, film("Prey", 2022), {}, 1200)


if __name__ == "__main__":
    unittest.main()
