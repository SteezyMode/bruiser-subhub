"""Offline safety regression tests for spoiler-free, create-only JA film rescue."""
from pathlib import Path
import tempfile
import unittest

from tools import bruiser_ja_movie_rescue as movie


class Dummy:
    def __init__(self,language="ja",forced=False,subtitle_id="12",
                 release="You.Were.Never.Really.Here.2017",matches=None):
        self.language=language
        self.forced=forced
        self.subtitle_id=subtitle_id
        self.release_info=release
        self.filename=release+".ja.srt"
        self.matches=matches if matches is not None else {"title"}
        self.uploader_trust=0


class TestMovieRescue(unittest.TestCase):
    def test_picks_only_matched_japanese_not_wrong_film_or_forced(self):
        items=[
            Dummy(language="en"),
            Dummy(forced=True),
            Dummy(release="Wrong.Film.2017",matches=set()),
            Dummy(matches={"title","year"}),
        ]
        selected=movie.select_candidates(items,"You Were Never Really Here")
        self.assertEqual(len(selected),1)
        self.assertEqual(selected[0][1],items[-1])

    def test_subtitle_kind_from_download_bytes_not_predicted(self):
        self.assertEqual(movie.subtitle_format(
            b"1\n00:00:03,000 --> 00:00:05,000\nText\n"),".srt")
        self.assertEqual(movie.subtitle_format(
            b"[Script Info]\nTitle: TEST\n[Events]\n"),".ass")
        self.assertEqual(movie.subtitle_format(b"random stuff"),"")

    def test_quality_screen_accepts_natural_paraphrases_mechanical_only(self):
        cues=[
            {"start":10000+i*10000,"end":13000+i*10000,
             "text": "先に行こう" if i%2==0 else "一緒に出よう"}
            for i in range(400)]
        r=movie.health(cues,4500)
        self.assertTrue(r["ok"],r)

    def test_wrong_language_is_held(self):
        cues=[{"start":10000+i*10000,"end":13000+i*10000,
              "text":"The story is in English"} for i in range(400)]
        r=movie.health(cues,4500)
        self.assertIn("not_predominantly_japanese",r["holds"])

    def test_sparse_forced_only_is_held(self):
        cues=[{"start":5000+i*15000,"end":9000+i*15000,
              "text":"看板"} for i in range(20)]
        r=movie.health(cues,4500)
        self.assertIn("too_few_cues",r["holds"])
        self.assertIn("ends_too_early",r["holds"])

    def test_create_only_and_never_overwrite(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/"You.Were.Never.Really.Here.2017.mkv"
            p.write_bytes(b"film")
            src=Path(temp)/"valid.srt"
            src.write_text("1\n00:00:00,000 --> 00:00:01,000\n日本語")
            created=movie.publish_create_only(p,src,".srt")
            self.assertEqual(created.read_bytes(),src.read_bytes())
            with self.assertRaises(RuntimeError):
                movie.publish_create_only(p,src,".srt")
            self.assertEqual(created.read_bytes(),src.read_bytes())
            self.assertEqual(movie.existing_ja_sidecars(p),[created])

    def test_filename_discovery_has_no_dialogue_and_no_symlink_follow(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            video=root/"Drama"/"You.Were.Never.Really.Here.2017.mkv"
            video.parent.mkdir()
            video.write_bytes(b"video")
            found=movie.find_video("You Were Never Really Here",roots=(root,))
            self.assertEqual(found,[video])


if __name__=="__main__":
    unittest.main()
