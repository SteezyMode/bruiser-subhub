"""Offline safety/coverage test for the second-pass English subtitle census."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import verify_english_coverage as verify


def row(path, kind='Movie', external=False):
    return {"english_source":"jellyfin_text_stream",
            "kind":kind, "series":"A show", "video_path":str(path),
            "title":path.stem,
            "english_stream_is_external": external,
            "japanese_status": "none_detected"}


class VerifyCoverageTests(unittest.TestCase):
    def setUp(self):
        self.t=tempfile.TemporaryDirectory()
        self.addCleanup(self.t.cleanup)
        self.root=Path(self.t.name)
        self.video=self.root/'Film.mkv'
        self.video.write_bytes(b'fake video')
        self.item=row(self.video)

    def test_probe_embedded_english_candidate(self):
        actual=verify.inspect(
            self.item,(self.root,),
            prober=lambda *_:{'ja':False,'embedded_en':3})
        self.assertEqual(actual["ffprobe_status"],"embedded_english_text_verified")
        self.assertEqual(actual["actual_stream_index"],3)

    def test_probe_japanese_detected_is_excluded(self):
        actual=verify.inspect(
            self.item,(self.root,),
            prober=lambda *_:{'ja':True,'embedded_en':3})
        self.assertEqual(actual["next_action"],"skip_already_has_japanese")

    def test_jellyfin_external_not_misclassified_embedded(self):
        x=row(self.video, external=True)
        actual=verify.inspect(
            x,(self.root,),
            prober=lambda *_:{'ja':False,'embedded_en':None})
        self.assertEqual(actual["ffprobe_status"],"jellyfin_external_text_unresolved")

    def test_bad_media_paths_rejected_without_probing(self):
        outside=self.root.parent/'unowned-media-do-not-read.mkv'
        x=row(outside)
        actual=verify.inspect(x,(self.root,),
              prober=lambda *_: self.fail('should not invoke ffprobe'))
        self.assertEqual(actual["ffprobe_status"],"video_unavailable")

    def test_extraction_sample_has_film_and_episode(self):
        films=[dict(row(self.video),ffprobe_status="embedded_english_text_verified",
                    actual_stream_index=3)]
        ep=self.root/'TV.E01.mkv'
        ep.write_bytes(b'fake')
        episodes=[dict(row(ep,'Episode'),
                       ffprobe_status="embedded_english_text_verified",
                       actual_stream_index=2)]
        selected=verify.sample_order(films+episodes,2)
        self.assertEqual(set(x["kind"] for x in selected), {"Movie","Episode"})
        seen=[]
        def reader(video,meta):
            seen.append((str(video),meta["embedded_en"]))
            return b'test',40,'embedded_english_text'
        result=verify.extract_sample(selected,(self.root,),2,reader=reader)
        self.assertEqual(result["extracted_valid_srt"],2)
        self.assertEqual(len(seen),2)

    def test_reject_source_mismatch_instead_of_counting_success(self):
        item=dict(self.item,ffprobe_status="embedded_english_text_verified",
                  actual_stream_index=1)
        result=verify.extract_sample([item],(self.root,),1,
                                     reader=lambda *a,**k:(b'a',40,'named_english_srt'))
        self.assertEqual(result["extraction_failed"],1)
        self.assertNotEqual(item["extraction_status"],"extracted_valid_srt")

    def test_report_selector_does_not_open_previous_verification_json(self):
        source=self.root/'en-no-ja-20261106T011929Z.json'
        source.write_text(json.dumps({'schema':'bruiser-english-without-japanese-v1',
                                      'items':[]}))
        (self.root/'en-no-ja-verified-20261107T000000Z.json').write_text('{}')
        self.assertEqual(verify.manifest_path(self.root),source)

    def test_no_symlink_manifest_directory(self):
        other=self.root/'folder'
        other.mkdir()
        link=self.root/'link'
        link.symlink_to(other, target_is_directory=True)
        with self.assertRaises(RuntimeError):
            verify.manifest_path(link)


if __name__=="__main__":
    unittest.main()
