"""Offline safety regression tests for spoiler-free, create-only JA film rescue."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import bruiser_ja_movie_rescue as movie


class Dummy:
    def __init__(self,language="ja",forced=False,subtitle_id="12",
                 release="You.Were.Never.Really.Here.2017",matches=None):
        self.provider_name="opensubtitles"
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

    def test_symbols_do_not_count_as_untranslated_language(self):
        # Observed 365-cue shape: 283 Japanese, 80 symbols, two short Latin cues.
        # The old 283/365 gate incorrectly held this film as 77.5% Japanese.
        cues=[]
        for i in range(365):
            phrase = "日本語です" if i<283 else ("♪…" if i<363 else "OK")
            start=int((103.56 + i*(4814.91/364))*1000)
            cues.append({"start":start,"end":start+1200,"text":phrase})
        out=movie.health(cues,5368.5,allow_offset_sec=30)
        self.assertTrue(out["ok"],out)
        self.assertEqual(out["language_bearing_cues"],285)
        self.assertEqual(out["symbols_only_cues"],80)
        self.assertEqual(out["japanese_fraction"],0.993)

    def test_actual_untranslated_letter_cues_still_fail(self):
        cues=[]
        for i in range(365):
            phrase = "字幕です" if i<265 else "EN"
            start=int((103.56 + i*(4814.91/364))*1000)
            cues.append({"start":start,"end":start+1200,"text":phrase})
        out=movie.health(cues,5368.5,allow_offset_sec=30)
        self.assertIn("not_predominantly_japanese",out["holds"])

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

    def test_bad_hash_match_does_not_stop_title_discovery(self):
        video=Path("/media/bigdisk-video/Movies/testfilm.mkv")
        class Provider:
            def __init__(self):self.calls=[]
            def search(self, query):
                self.calls.append((query.title, query.file_path))
                return [Dummy(subtitle_id="same",matches={"title"})] if query.file_path else [
                    Dummy(subtitle_id="same",matches={"title"}),
                    Dummy(subtitle_id="alternative",release="You Were Never Really Here 2017 WEB DL",matches={"title","year"})]
        p=Provider()
        candidates=movie.search_movie_sources(p,video,"You Were Never Really Here",
                                             query_type=lambda **args:type("Q",(),{**{"file_path":""},**args})())
        self.assertEqual([item.subtitle_id for item in candidates],["same","alternative"])
        self.assertEqual(len(p.calls),2)
        self.assertTrue(p.calls[0][1])
        self.assertFalse(p.calls[1][1])

    def test_private_staging_keeps_bad_source_for_reuse_without_media_writes(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp)
            video=base/"You.Were.Never.Really.Here.2017.mp4"
            video.write_bytes(b"video")
            content=b"1\\n00:00:01,000 --> 00:00:03,000\\nBad English-only captions\\n"
            source_result=Dummy()
            with patch.object(movie,"OUT_ROOT",base/"private-staged"):
                report={"ok":False,"holds":["not_predominantly_japanese"],"non_japanese_latin_word_cues":1}
                source,metadata=movie.stage_private_candidate(video,source_result,content,".srt",report)
                self.assertTrue(source.exists())
                self.assertEqual(source.read_bytes(),content)
                self.assertFalse(list(base.glob("*.ja.srt")))
                self.assertIn("quality_gate",metadata.read_text())
                self.assertNotIn("Bad English-only captions",metadata.read_text())
                # Repeat of same candidate must not overwrite or create sidecars.
                again,_=movie.stage_private_candidate(video,source_result,content,".srt",report)
                self.assertEqual(again,source)

    def test_resume_private_candidate_without_provider_calls_or_overwrite(self):
        import hashlib
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp)
            video=base/"You.Were.Never.Really.Here.2017.mp4"
            video.write_bytes(b"original film")
            raw=b"provider subtitle source bytes"
            aligned_file=base/"alignment-output.srt"
            aligned_file.write_bytes(b"synced subtitle source bytes")
            cues=[]; corrected=[]
            for i in range(365):
                phrase="日本語です" if i<283 else ("♪…" if i<363 else "OK")
                start=int((103.56+i*(4814.91/364))*1000)
                cues.append({"start":start,"end":start+1200,"text":phrase})
                corrected.append({"start":start-19330,"end":start+1200-19330,
                                  "text":phrase})
            with patch.object(movie,"OUT_ROOT",base/"private"):
                assessment={"ok":False,"holds":["not_predominantly_japanese"],
                            "video_seconds":5368.5}
                stage,report=movie.stage_private_candidate(
                    video,Dummy(),raw,".srt",assessment,
                    sync={"ok":True,"shift_ms":-19330},aligned=aligned_file)
                def fake_cues(path):
                    return cues if Path(path)==stage else corrected
                with patch("services.sync_preview.load_cues",side_effect=fake_cues,create=True):
                    with patch.object(movie,"has_embedded_japanese",return_value=False):
                        movie.resume_staged(video,5368.5,str(report),apply=False)
                        self.assertEqual(list(base.glob("*.ja.srt")),[])
                        movie.resume_staged(video,5368.5,str(report),apply=True)
                        result=video.with_name(video.stem+
                            ".Bruiser Sourced Unverified.ja.srt")
                        self.assertEqual(result.read_bytes(),aligned_file.read_bytes())
                        self.assertEqual(video.read_bytes(),b"original film")
                        self.assertEqual(stage.read_bytes(),raw)
                        with self.assertRaises(RuntimeError):
                            movie.resume_staged(video,5368.5,str(report),apply=True)

    def test_ffsubsync_timeout_is_a_hold_not_a_crash(self):
        import subprocess
        with patch.object(movie.subprocess,"run",side_effect=subprocess.TimeoutExpired(["ffsubsync"],600)):
            result=movie.sync_candidate(Path("/tmp/movie.mp4"),Path("/tmp/candidate.srt"),
                                        Path("/tmp/aligned.srt"),parse_shift=lambda _:0)
        self.assertEqual(result,{"ok":False,"hold":"ffsubsync_timeout"})

    def test_non_japanese_cues_are_counted_without_dialogue_disclosure(self):
        cues=[{"start":10000+i*10000,"end":13000+i*10000,
              "text":"日本語です" if i%4 else "English dialogue"} for i in range(400)]
        result=movie.health(cues,4500)
        self.assertEqual(result["non_japanese_latin_word_cues"],100)
        self.assertEqual(result["non_japanese_non_latin_cues"],0)
        self.assertEqual(sum(result["latin_word_cues_by_film_quarter"]),100)
        self.assertNotIn("English dialogue",str(result))
        self.assertIn("not_predominantly_japanese",result["holds"])

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

    def test_saved_japanese_original_preserved_with_separate_synced_copy(self):
        with tempfile.TemporaryDirectory() as temp:
            video=Path(temp)/"You.Were.Never.Really.Here.2017.mkv"
            video.write_bytes(b"film")
            original=video.with_name(video.stem+".ja.srt")
            original.write_text("original Japanese track")
            aligned=Path(temp)/"aligned.srt"
            aligned.write_text("corrected Japanese track")
            published=movie.publish_synced_alternative(video,aligned,".srt")
            self.assertEqual(original.read_text(),"original Japanese track")
            self.assertEqual(published.read_text(),"corrected Japanese track")
            self.assertTrue(published.name.endswith(".BruiserSynced.ja.srt"))
            with self.assertRaises(FileExistsError):
                movie.publish_synced_alternative(video,aligned,".srt")

    def test_late_subtitle_is_not_rejected_before_ffsubsync(self):
        cues=[{"start":5000+i*10000,"end":8500+i*10000,
              "text":"これは自然な日本語です"} for i in range(400)]
        # Extend the final line beyond the video by 13 seconds: an offset
        # candidate must not be rejected before ffsubsync can correct it.
        cues[-1]["start"]=4500*1000+9000
        cues[-1]["end"]=4500*1000+13000
        pre=movie.health(cues,4500,allow_offset_sec=30)
        self.assertNotIn("invalid_timing",pre["holds"])
        post=movie.health(cues,4500)
        self.assertIn("invalid_timing",post["holds"])

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
