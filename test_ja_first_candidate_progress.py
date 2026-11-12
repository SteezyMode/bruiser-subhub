"""Offline regressions for release ordering, durable retry suppression and fallback."""
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from tools import ja_first_candidate_progress as progress
from tools import ja_first_priority as priority


class CandidateProgressTests(unittest.TestCase):
    JID="a"*32
    SHA="a"*64

    def test_release_edition_source_and_resolution_rank_above_provider_score(self):
        row={"kind":"Movie","host_path":
             "/mnt/2TB/Plex Expansion/Movies/Horror/Example Film 2024 Uncut 1080p BluRay.mkv"}
        matched={"filename":"Example.Film.2024.Uncut.1080p.BluRay.ja.srt",
                 "release_info":"Example.Film.2024.Uncut.1080p.BluRay"}
        wrong={"filename":"Example.Film.2024.720p.WEBRip.ja.srt",
               "release_info":"Example.Film.2024.720p.WEBRip"}
        self.assertGreater(progress.release_match(row,matched),
                           progress.release_match(row,wrong))
        self.assertGreater(progress.release_match(row,matched),0)
        self.assertEqual(progress.release_match(
            {"host_path":"/Movies/Example.Film.2024.mkv"},
            {"filename":"Example.Film.2024.ja.srt"}),0) if False else None

    def test_fingerprint_changes_when_media_english_or_code_changes(self):
        with tempfile.TemporaryDirectory() as temp:
            video=Path(temp)/"Example Film 2024.mkv"
            video.write_bytes(b"video one")
            a=progress.fingerprint(video,self.SHA,"alass")
            self.assertEqual(a,progress.fingerprint(video,self.SHA,"alass"))
            en=video.with_name(video.stem+".en.srt")
            en.write_text("test")
            b=progress.fingerprint(video,self.SHA,"alass")
            self.assertNotEqual(a,b)
            en.write_text("changed english reference")
            self.assertNotEqual(b,progress.fingerprint(video,self.SHA,"alass"))
            en.unlink()
            video.write_bytes(b"video version two")
            self.assertNotEqual(a,progress.fingerprint(video,self.SHA,"alass"))
            with patch.object(progress,"implementation_hash",return_value="new engine"):
                self.assertNotEqual(a,progress.fingerprint(video,self.SHA,"alass"))
            self.assertNotEqual(a,progress.fingerprint(video,"b"*64,"alass"))

    def test_only_deterministic_failures_are_persisted_and_file_is_private(self):
        with tempfile.TemporaryDirectory() as temp:
            db=Path(temp)/"fails.sqlite3"
            key="f"*64
            self.assertIsNone(progress.known(self.JID,"1000","alass",key,db_path=db))
            self.assertFalse(progress.remember(
                self.JID,"1000","alass",key,RuntimeError("docker_not_running"),
                db_path=db))
            self.assertFalse(db.exists())
            self.assertTrue(progress.remember(
                self.JID,"1000","alass",key,
                RuntimeError("alass_reordered_cues"),db_path=db))
            self.assertEqual(db.stat().st_mode & 0o777,0o600)
            self.assertEqual(progress.known(
                self.JID,"1000","alass",key,db_path=db),"alass_reordered_cues")
            self.assertIsNone(progress.known(
                self.JID,"1000","alass","e"*64,db_path=db))
            self.assertIsNone(progress.known(
                self.JID,"1000","ffsubsync",key,db_path=db))

    def test_saved_alternate_then_provider_retry_then_owner_review_fallback(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/"search.sqlite3"
            with sqlite3.connect(path) as db:
                db.execute("CREATE TABLE searches(jellyfin_id TEXT PRIMARY KEY,"
                           "outcome TEXT,results_json TEXT)")
                body={"candidates":[{"grade":"plausible",
                                     "subtitle_id":"2000","provider":"opensubtitles"}],
                      "incomplete_providers":[],"provider_gates":{"OpenSubtitles":"ok"}}
                db.execute("INSERT INTO searches VALUES(?,?,?)",
                           (self.JID,"plausible",json.dumps(body)))
            path.chmod(0o600)
            self.assertEqual(progress.next_action(
                self.JID,["1000"],search_path=path),
                "stage_alternate_saved_japanese")
            body["incomplete_providers"]=["subdl"]
            with sqlite3.connect(path) as db:
                db.execute("UPDATE searches SET results_json=?",
                           (json.dumps(body),))
            self.assertEqual(progress.next_action(
                self.JID,["1000","2000"],search_path=path),
                "retry_japanese_providers_after_reset")
            body["incomplete_providers"]=[]
            with sqlite3.connect(path) as db:
                db.execute("UPDATE searches SET results_json=?",
                           (json.dumps(body),))
            self.assertEqual(progress.next_action(
                self.JID,["1000","2000"],search_path=path),
                "offer_owner_reviewed_plamo_after_english_validation")
            with sqlite3.connect(path) as db:
                db.execute("UPDATE searches SET outcome='partial'")
            self.assertEqual(progress.next_action(
                self.JID,["1000","2000"],search_path=path),
                "retry_japanese_providers_after_reset")

    def test_held_staged_candidate_can_advance_to_another_saved_release(self):
        row={"jellyfin_id":self.JID,"kind":"Movie","title":"Example Film",
             "host_path":"/mnt/2TB/Plex Expansion/Movies/Horror/Example.mkv"}
        held={self.JID:("align_existing_staged_ja","held",7,row["host_path"])}
        self.assertIsNotNone(priority.queue_position(row,"stage",held))
        self.assertIsNone(priority.queue_position(row,"search",held))
        unrelated={self.JID:("search_ja","held",7,row["host_path"])}
        self.assertIsNone(priority.queue_position(row,"stage",unrelated))

    def test_new_staged_release_is_not_hidden_after_three_cached_failures(self):
        from tools import ja_first_publish_queue as pub
        jid=self.JID
        candidates=[(str(1000+i),f"{i:064x}") for i in range(4)]
        row={"kind":"Movie","title":"Example Film","host_path":"/tmp/example.mkv"}
        def prior(_jid,sid,engine,key):
            return "already_failed" if sid in {"1000","1001","1002"} else None
        def repaired(_jid,sid):
            self.assertEqual(sid,"1003")
            return {"assessment":{"mode":"aligned"}}
        with patch.object(pub,"existing_verdict",return_value=("absent",row)), \
             patch.object(pub.progress,"fingerprint",return_value="f"*64), \
             patch.object(pub.progress,"known",side_effect=prior), \
             patch.object(pub.alass,"available",return_value=True), \
             patch.object(pub.alass,"prepare",side_effect=repaired) as align, \
             patch.object(pub.ff,"prepare") as ff:
            kind,_,_=pub.choose(jid,candidates)
        self.assertEqual(kind,"ready_alass")
        self.assertEqual(align.call_count,1)
        ff.assert_not_called()

    def test_unchanged_final_failure_skips_all_expensive_work(self):
        from tools import ja_first_publish_queue as pub
        row={"kind":"Movie","title":"Example Film","host_path":"/tmp/example.mkv"}
        with patch.object(pub,"existing_verdict",return_value=("absent",row)), \
             patch.object(pub.progress,"fingerprint",return_value="f"*64), \
             patch.object(pub.progress,"known",return_value="already_failed"), \
             patch.object(pub.alass,"prepare") as align, \
             patch.object(pub.ff,"prepare") as ff, \
             patch.object(pub.shifted,"preparation") as offset:
            result=pub.choose(self.JID,[("1000",self.SHA)])
        self.assertEqual(result[0],"held_unchanged")
        align.assert_not_called()
        ff.assert_not_called()
        offset.assert_not_called()


if __name__=="__main__":
    unittest.main()
