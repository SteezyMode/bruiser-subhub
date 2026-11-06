"""Read-only, full-library English-text/no-Japanese coverage audit tests."""
from pathlib import Path
import csv
import json
import tempfile
import unittest
from unittest.mock import patch

from tools import audit_english_without_japanese as audit


def item(video, *, en=False, ja=False, codec="subrip", forced=False, kind="Movie"):
    subs=[]
    if en:
        subs.append({"Type":"Subtitle","Language":"eng","Codec":codec,
                     "Index":3,"IsForced":False,"IsExternal":False})
    if ja:
        subs.append({"Type":"Subtitle","Language":"ja-JP",
                     "Codec":"subrip","Index":4,"IsForced":forced})
    return {"Type":kind,"Id":"test-"+video.stem, "Path":str(video),
            "Name":video.stem, "SeriesName":"Example",
            "ParentIndexNumber":1, "IndexNumber":1,
            "MediaStreams":[{"Type":"Audio","Language":"eng"},*subs]}


def okay(*args,**kwargs):
    return b"valid fake English",24,"named_english_srt"


class AuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.video=self.root/"Film.2024.mkv"
        self.video.write_bytes(b"media")
        self.english=self.root/"Film.2024.en.srt"

    def test_external_english_srt_no_japanese_is_candidate(self):
        self.english.write_bytes(b"dummy")
        r=audit.classify(self.video,item(self.video),source_reader=okay)
        self.assertEqual(r["category"],"candidate")
        self.assertEqual(r["english_status"],"parsed_external_srt")
        self.assertEqual(r["english_cues"],24)
        self.assertEqual(r["queue_readiness"],"source_text_ready")

    def test_existing_japanese_overrides_english(self):
        self.english.write_bytes(b"dummy")
        (self.root/"Film.2024.ja.PLaMo8B.srt").write_bytes(b"existing")
        r=audit.classify(self.video,item(self.video),source_reader=okay)
        self.assertEqual(r["category"],"has_japanese")

    def test_embedded_japanese_overrides_english_even_without_sidecar(self):
        r=audit.classify(self.video,item(self.video,en=True,ja=True))
        self.assertEqual(r["category"],"has_japanese")
        self.assertEqual(r["japanese_status"],"japanese_media_stream")

    def test_forced_only_japanese_does_not_claim_dialogue(self):
        r=audit.classify(self.video,item(self.video,en=True,ja=True,forced=True))
        self.assertEqual(r["category"],"candidate")
        self.assertEqual(r["english_status"],"jellyfin_text_track_unverified")

    def test_embedded_text_candidate_but_bitmap_not_text(self):
        self.assertEqual(audit.classify(
            self.video,item(self.video,en=True,codec="ass"))["category"],"candidate")
        self.assertEqual(audit.classify(
            self.video,item(self.video,en=True,codec="hdmv_pgs_subtitle")
        )["category"],"missing_english_text")

    def test_bad_external_srt_does_not_become_source_ready(self):
        self.english.write_bytes(b"malformed")
        def bad(*args,**kwargs):
            raise RuntimeError("invalid_srt")
        r=audit.classify(self.video,item(self.video),source_reader=bad)
        self.assertEqual(r["category"],"invalid_english_srt")

    def test_missing_streams_are_probed_instead_of_assuming_no_japanese(self):
        x=item(self.video)
        del x["MediaStreams"]
        probe=lambda *_: {"ja":True,"embedded_en":None}
        r=audit.classify(self.video,x,probe=probe)
        self.assertEqual(r["category"],"has_japanese")
        self.assertEqual(r["japanese_status"],"japanese_media_stream")

    def test_full_catalog_and_private_create_only_reports(self):
        self.english.write_bytes(b"valid")
        other=self.root/"Film.2025.mkv"
        other.write_bytes(b"media")
        other_ja=self.root/"Film.2025.ja.srt"
        other_ja.write_bytes(b"existing")
        items=[item(self.video,en=True),item(other,en=True)]
        class FakeClient:
            pass
        with patch.object(audit.library,"catalog",return_value={
                str(x["Path"]):x for x in items}), \
             patch.object(audit,"prior_jellyfin_only",return_value=set()):
            summary,rows,unresolved=audit.collect(
                client=FakeClient(), roots=(self.root,), source_reader=okay)
        self.assertEqual(summary["english_no_japanese_candidates"],1)
        self.assertEqual(summary["has_japanese"],1)
        self.assertEqual(len(rows),1)
        folder=self.root/"report"
        audit.save_private(folder,"sample",summary,rows,unresolved)
        self.assertEqual(json.loads((folder/"sample.json").read_text())
                         ["summary"]["english_no_japanese_candidates"],1)
        self.assertEqual(len(list(csv.DictReader(
            (folder/"sample.csv").open()))),1)
        self.assertEqual(folder.stat().st_mode & 0o777,0o700)
        self.assertEqual((folder/"sample.csv").stat().st_mode & 0o777,0o600)
        with self.assertRaises(FileExistsError):
            audit.save_private(folder,"sample",summary,rows,unresolved)


if __name__=="__main__":
    unittest.main()
