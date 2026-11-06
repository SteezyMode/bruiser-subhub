"""Offline, no-GPU tests of the queue-owned PLaMo subtitle handoff."""
from pathlib import Path
import json
import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from tools import subhub_plamo_handoff as ai


class HandoffTests(unittest.TestCase):
    def db(self, folder):
        path = Path(folder) / "coverage.sqlite3"
        db=sqlite3.connect(path)
        db.executescript("""
            CREATE TABLE media (
                path TEXT PRIMARY KEY,jellyfin_id TEXT,
                kind TEXT,title TEXT,series TEXT,en_text INTEGER
            );
            CREATE TABLE tasks (
                path TEXT,target TEXT,action TEXT,state TEXT,
                priority INTEGER,active INTEGER
            );
        """)
        db.execute(
            "INSERT INTO media VALUES(?,?,?,?,?,?)",
            ("/media/A/movie.mkv","fid_A","Movie","Example film","",1))
        db.execute(
            "INSERT INTO media VALUES(?,?,?,?,?,?)",
            ("/media/B/episode.mkv","fid_B","Episode","The Episode","The Series",0))
        db.execute(
            "INSERT INTO tasks VALUES(?,?,?,?,?,?)",
            ("/media/A/movie.mkv","ja","validate_english_for_ja_fallback",
             "pending",51,1))
        db.execute(
            "INSERT INTO tasks VALUES(?,?,?,?,?,?)",
            ("/media/B/episode.mkv","ja","recover_english_for_ja_fallback",
             "pending",61,1))
        db.commit()
        db.close()
        path.chmod(0o600)
        return path

    def test_movie_held_checkpoint_survives_restart_and_excludes_fake_japanese(self):
        from types import SimpleNamespace
        import re
        from tools import subhub_plamo_handoff as ai
        def cue(i):
            return {"number":i+1,"start":"00:01:00,000",
                    "end":"00:01:02,000","english":f"Input {i+1}"}
        cues=[cue(i) for i in range(4)]
        class Engine:
            SPOKEN="translated"
            SOLO_SDH="sdh_only"
            small=SimpleNamespace(JP=re.compile("[\u3040-\u30ff\u4e00-\u9fff]"))
            real=SimpleNamespace(is_non_dialogue_caption=lambda text:False)
            def verify_checkpoints(self, db, cues):
                raise AssertionError("existing verifier must not silently accept held rows")
            @staticmethod
            def jellyfin_srt(output):
                assert all(x["status"]!="held_translation" for x in output)
                return "valid japanese srt",len(output)
        with tempfile.TemporaryDirectory() as temp:
            with sqlite3.connect(Path(temp)/"progress.sqlite3") as db:
                db.execute("CREATE TABLE translation (idx INTEGER,id INTEGER,"
                           "start TEXT,end TEXT,english TEXT,japanese TEXT,"
                           "status TEXT,seconds REAL)")
                rows=[(0,1,cues[0]["start"],cues[0]["end"],cues[0]["english"],
                       "これは字幕","translated",0.5),
                      (1,2,cues[1]["start"],cues[1]["end"],cues[1]["english"],
                       "","held_translation",0.5),
                      (2,3,cues[2]["start"],cues[2]["end"],cues[2]["english"],
                       "続けます","translated",0.5)]
                db.executemany("INSERT INTO translation VALUES (?,?,?,?,?,?,?,?)", rows)
                output=ai.verify_movie_checkpoints(Engine(),db,cues)
                self.assertEqual(len(output),3)
                self.assertEqual(ai.held_summary(output)[0]["number"],2)
                with self.assertRaisesRegex(RuntimeError,"checkpoint_source_mismatch"):
                    changed=list(cues)
                    changed[1]=dict(cues[1],english="changed cue")
                    ai.verify_movie_checkpoints(Engine(),db,changed)
                ja,count=Engine.jellyfin_srt(
                    [x for x in output if x["status"]!=ai.HELD_STATUS])
                self.assertEqual(count,2)
                self.assertTrue(ja)

    def test_movie_held_budget_guards_quality(self):
        from tools import subhub_plamo_handoff as ai
        with self.assertRaisesRegex(RuntimeError,"too_many_consecutive_held"):
            ai.held_summary([{"status":ai.HELD_STATUS} for _ in range(3)])
        with self.assertRaisesRegex(RuntimeError,"too_many_held_cues"):
            ai.held_summary(
                [{"status":ai.HELD_STATUS if i%2==0 else "translated"}
                 for i in range(22)])

    def test_malformed_one_cue_is_recoverable_but_infrastructure_errors_are_not(self):
        def bad(request, port, english, history):
            raise RuntimeError("cue_model_error_after_retry:empty_or_malformed_model_output")
        ja,usage,status=ai.recover_held_cue(
            None,bad,18888,"Hello",[("Yes","はい")],"translated")
        self.assertEqual(status,"held_non_japanese")
        self.assertEqual(ja,"")
        def failure(request, port, english, history):
            raise RuntimeError("GPU_OFFLOAD_NOT_ACTIVE")
        with self.assertRaisesRegex(RuntimeError,"GPU_OFFLOAD_NOT_ACTIVE"):
            ai.recover_held_cue(None,failure,18888,"Hello",[],"translated")

    def test_movie_thermal_hysteresis_preserves_abort_and_isolated_runtime(self):
        from types import SimpleNamespace
        batch=SimpleNamespace(GPU_PAUSE=73.0,GPU_RESUME=67.0,
                              GPU_ABORT=83.0)
        ai.movie_thermal_limits(batch)
        self.assertEqual((batch.GPU_PAUSE,batch.GPU_RESUME,batch.GPU_ABORT),
                         (78.0,72.0,83.0))

    def test_failed_spoken_cue_retries_with_fresh_history(self):
        requests=[]
        def retry(request,port,english,history):
            requests.append(list(history))
            if history:
                return ("Paris", {}, "held_non_japanese")
            return ("パリ", {}, "translated")
        result=ai.recover_held_cue(None,retry,18888,"Paris",
                                   [("Hello","こんにちは")],"translated")
        self.assertEqual(result[0],"パリ")
        self.assertEqual(requests,[[("Hello","こんにちは")],[]])

    def test_cue_recovery_never_checkpoints_untranslated_latin(self):
        requests=[]
        def retry(request,port,english,history):
            requests.append(history)
            return ("Paris",{}, "held_non_japanese")
        result=ai.recover_held_cue(None,retry,18888,"Paris",
                                   [("Hi","やあ")],"translated")
        self.assertEqual(result[2],"held_non_japanese")
        self.assertEqual(len(requests),2)

    def test_only_source_exhausted_targets_offered(self):
        with tempfile.TemporaryDirectory() as t:
            path=self.db(t)
            with ai.safe_db(path) as db:
                rows=ai.eligible(db)
                self.assertEqual(len(rows),2)
                self.assertEqual(rows[0]["jellyfin_id"],"fid_A")
                ai.validate_row(rows[0])
                with self.assertRaisesRegex(RuntimeError,"japanese_sourcing_not_exhausted"):
                    ai.validate_row(rows[1])
                self.assertEqual(ai.eligible(db,"fid_A")[0]["series"],"")

    def test_extra_blank_srt_blocks_normalized_before_sync(self):
        import re
        class Sync:
            @staticmethod
            def parse_cues(raw):
                text=raw.decode("utf-8-sig").strip()
                blocks=re.split(r"\r?\n[ \t]*\r?\n",text)
                result=[]
                for block in blocks:
                    lines=block.splitlines()
                    if len(lines)<3 or "-->" not in lines[1]:
                        raise RuntimeError("malformed_srt_cue")
                    result.append(lines)
                return result
        # An isolated empty pseudo-cue between two valid subtitle cues.
        raw=(b"1\n00:00:01,000 --> 00:00:02,000\nHello\n"
             b"\n\n\n"
             b"2\n00:00:03,000 --> 00:00:04,000\nGoodbye\n"
             b"\n")
        with self.assertRaisesRegex(RuntimeError,"malformed_srt_cue"):
            Sync.parse_cues(raw)
        cleaned=ai.normalize_external_english(raw,Sync)
        self.assertEqual(len(Sync.parse_cues(cleaned)),2)
        self.assertIn(b"Goodbye",cleaned)
        self.assertEqual(
            [x for x in raw.decode().splitlines() if x.strip()],
            [x for x in cleaned.decode().splitlines() if x.strip()])
        # Original subtitle bytes remain unchanged, only private copy cleaned.
        self.assertIn(b"\n\n\n",raw)
        self.assertNotIn(b"\n\n\n",cleaned)

    def test_srt_normalization_does_not_drop_bad_extra_text(self):
        class Sync:
            @staticmethod
            def parse_cues(raw):
                if b"ADVERTISEMENT" in raw:
                    raise RuntimeError("malformed_srt_cue")
                return [{"start":1}]
        raw=(b"1\n00:00:01,000 --> 00:00:02,000\nHello"
             b"\n\n\nADVERTISEMENT\n")
        with self.assertRaisesRegex(RuntimeError,"malformed_srt_cue"):
            ai.normalize_external_english(raw,Sync)

    def test_rewind_to_zero_malformed_terminal_cue_is_quarantined(self):
        """Actual As Above So Below provider failure pattern (without media)."""
        import re
        class Sync:
            @staticmethod
            def parse_cues(raw):
                blocks=re.split(r"\n[ \t]*\n",raw.decode().strip())
                result=[]
                for block in blocks:
                    lines=block.splitlines()
                    ix=int(bool(lines[0].isdigit()))
                    if len(lines)<ix+2:
                        raise RuntimeError("malformed_srt_cue")
                    match=re.fullmatch(
                        r"(\d{2}:\d{2}:\d{2},\d{3}) --> "
                        r"(\d{2}:\d{2}:\d{2},\d{3})",lines[ix])
                    if match is None:
                        raise RuntimeError("bad_srt_timestamp")
                    h,m,sec=match.group(2).split(":")
                    end=(int(h)*3600+int(m)*60+float(sec.replace(",",".")))*1000
                    result.append({"end":end})
                return result
        blocks=[]
        for i in range(1,151):
            t=i*21
            def stamp(seconds):
                return f"{seconds//3600:02}:{seconds//60%60:02}:{seconds%60:02},000"
            blocks.append(
                f"{i}\n{stamp(t)} --> {stamp(t+1)}\nCue number {i}")
        original=("\n\n".join(blocks)+
                  "\n\n\n\n151\n00:00:0,500 --> 00:00:2,00\nJUNK\n")
        self.assertEqual(len(Sync.parse_cues(("\n\n".join(blocks)).encode())),150)
        # The raw sample deliberately includes redundant blank lines. The
        # normalizer handles these BEFORE examining the bad terminal clock.
        normalized_separators=re.sub(
            r"\n[ \t]*\n(?:[ \t]*\n)+","\n\n",original)
        with self.assertRaisesRegex(RuntimeError,"bad_srt_timestamp"):
            Sync.parse_cues(normalized_separators.encode())
        clean=ai.normalize_external_english(original.encode(),Sync)
        self.assertEqual(len(Sync.parse_cues(clean)),150)
        self.assertNotIn(b"JUNK",clean)
        self.assertIn(b"JUNK",original.encode())
        self.assertEqual(clean.decode().splitlines()[-1],"Cue number 150")

    def test_invalid_terminal_timestamp_not_silently_quarantined(self):
        import re
        class Sync:
            @staticmethod
            def parse_cues(raw):
                blocks=re.split(r"\n[ \t]*\n",raw.decode().strip())
                out=[]
                for block in blocks:
                    lines=block.splitlines()
                    ix=int(bool(lines[0].isdigit()))
                    if len(lines)<ix+2:
                        raise RuntimeError("malformed_srt_cue")
                    m=re.fullmatch(
                        r"(\d{2}):(\d{2}):(\d{2}),(\d{3}) --> "
                        r"(\d{2}):(\d{2}):(\d{2}),(\d{3})",lines[ix])
                    if not m:
                        raise RuntimeError("bad_srt_timestamp")
                    out.append({"end":(int(m[5])*3600+int(m[6])*60+int(m[7]))*1000})
                return out
        originals=[]
        for i in range(1,151):
            minute=i//2
            second=i%2*30
            originals.append(
                f"{i}\n01:{minute:02}:{second:02},000 --> "
                f"01:{minute:02}:{second+1:02},000\nLine")
        source="\n\n".join(originals)
        with self.assertRaisesRegex(RuntimeError,"bad_srt_timestamp"):
            ai.normalize_external_english(
                (source+"\n\n151\n00:50:0,500 --> 00:50:2,00\nReal-looking\n").encode(),
                Sync)

    def test_explicit_new_movie_requires_verified_jellyfin_id_and_path(self):
        from types import SimpleNamespace
        jid="d789e397319aad9a860633811b528b40"
        with tempfile.TemporaryDirectory() as folder:
            movie=Path(folder)/"As.Above.So.Below.2014.mp4"
            movie.write_bytes(b"synthetic-movie")
            path_gate=lambda path:Path(path)
            class Client:
                def get(self, path):
                    self_checked = "/Items/" + jid
                    assert path == self_checked
                    return {"Id":jid,"Type":"Movie",
                            "Path":str(movie),"Name":"As Above, So Below"}
            source=SimpleNamespace(NativeJellyfin=Client)
            row=ai.explicit_movie_pilot(jid,str(movie),source,path_gate)
            self.assertEqual(row["path"],str(movie))
            self.assertEqual(row["kind"],"Movie")
            self.assertEqual(row["action"],"explicit_owner_movie_pilot")
            self.assertEqual(row["jellyfin_id"],jid)
            with self.assertRaisesRegex(RuntimeError,"invalid_explicit_jellyfin_id"):
                ai.explicit_movie_pilot("invalid",str(movie),source,path_gate)
            with self.assertRaisesRegex(RuntimeError,"absolute_explicit_movie_path"):
                ai.explicit_movie_pilot(jid,"movie.mp4",source,path_gate)

    def test_explicit_new_movie_refuses_jellyfin_type_and_mismatch(self):
        from types import SimpleNamespace
        jid="d789e397319aad9a860633811b528b40"
        with tempfile.TemporaryDirectory() as folder:
            movie=Path(folder)/"Movie.mp4"
            movie.write_bytes(b"synthetic")
            def gate(path): return Path(path)
            class Client:
                item={"Id":jid,"Type":"Episode",
                      "Path":str(movie),"Name":"Example"}
                def get(self,path): return self.item
            cli=Client()
            source=SimpleNamespace(NativeJellyfin=lambda:cli)
            with self.assertRaisesRegex(RuntimeError,"jellyfin_movie_identity"):
                ai.explicit_movie_pilot(jid,str(movie),source,gate)
            cli.item={"Id":jid,"Type":"Movie",
                      "Path":"/wrong/place.mp4","Name":"Example"}
            with self.assertRaisesRegex(RuntimeError,"jellyfin_movie_identity"):
                ai.explicit_movie_pilot(jid,str(movie),source,gate)
            cli.item={"Id":jid,"Type":"Movie",
                      "Path":str(movie),"Name":"Example"}
            movie.unlink()
            with self.assertRaisesRegex(RuntimeError,"explicit_movie_file_missing"):
                ai.explicit_movie_pilot(jid,str(movie),source,gate)

    def test_initial_search_candidate_must_not_translate(self):
        row={"jellyfin_id":"a","path":"/media/a.mkv",
             "target":"ja","kind":"Movie","state":"pending",
             "english_text":1,"action":"search_ja"}
        with self.assertRaisesRegex(RuntimeError,"japanese_sourcing_not_exhausted"):
            ai.validate_row(row)

    def test_english_indicated_not_equal_verified_ready(self):
        row={"jellyfin_id":"a","path":"/media/a.mkv",
             "target":"ja","kind":"Movie","state":"pending",
             "english_text":0,"action":"validate_english_for_ja_fallback"}
        with self.assertRaisesRegex(RuntimeError,"english_text_not_indicated"):
            ai.validate_row(row)

    def test_public_queue_db_refused(self):
        with tempfile.TemporaryDirectory() as t:
            path=self.db(t)
            path.chmod(0o644)
            with self.assertRaisesRegex(RuntimeError,"private_coverage_queue"):
                ai.safe_db(path)

    def test_media_item_folders_distinct_and_stable(self):
        with tempfile.TemporaryDirectory() as t:
            p1=ai.private_folder("a","/media/1.mkv",t)
            p2=ai.private_folder("b","/media/1.mkv",t)
            self.assertNotEqual(p1,p2)
            self.assertEqual(p1,ai.private_folder("a","/media/1.mkv",t))
            self.assertTrue(p1.name.startswith("ja-"))

    def test_status_file_atomic_and_private(self):
        with tempfile.TemporaryDirectory() as t:
            path=Path(t)/"state.json"
            ai.atomic_json(path,{"result":"checkpointed"})
            self.assertEqual(json.loads(path.read_text())["result"],"checkpointed")
            self.assertEqual(path.stat().st_mode & 0o077,0)
            ai.atomic_json(path,{"result":"resumed"})
            self.assertEqual(json.loads(path.read_text())["result"],"resumed")

    def test_state_symlink_refused(self):
        with tempfile.TemporaryDirectory() as t:
            target=Path(t)/"target.json"
            target.write_text("{}")
            path=Path(t)/"state.json"
            path.symlink_to(target)
            with self.assertRaisesRegex(RuntimeError,"unsafe_state_symlink"):
                ai.atomic_json(path,{})

    def test_existing_translator_pid_blocks(self):
        with tempfile.TemporaryDirectory() as t:
            path=Path(t)/"batch.pid"
            path.write_text(str(os.getpid()))
            path.chmod(0o600)
            self.assertTrue(ai.other_translation_running(path))
            path.write_text("999999999")
            self.assertFalse(ai.other_translation_running(path))

    def test_unsafe_translator_pid_file_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            path=Path(t)/"batch.pid"
            path.write_text("not_a_pid")
            path.chmod(0o600)
            with self.assertRaisesRegex(RuntimeError,"invalid_previous_translation_pid_file"):
                ai.other_translation_running(path)

    def test_source_batch_blocks_gpu_even_before_hardware_use(self):
        row={"jellyfin_id":"x"}
        with patch.object(ai,"recent_running_source",return_value=True), \
             patch.object(ai,"modules",side_effect=AssertionError("no modules")):
            with self.assertRaisesRegex(RuntimeError,"source_batch_still_running"):
                ai.translate(row,Path("/tmp/nonexistent"),
                             (None,None,None,None,None,None,None))

    def test_missing_source_is_not_translated(self):
        class Daily:
            @staticmethod
            def already_ja(video): return False
            @staticmethod
            def english_srt(video): return None
        info={"audio_en":True,"ja":False,"embedded_en":None}
        with tempfile.TemporaryDirectory() as folder:
            video=Path(folder)/"movie.mkv"
            video.write_bytes(b"not-a-video (preflight fixture only)")
            with self.assertRaisesRegex(RuntimeError,"english_text_source_not_available"):
                ai.saved_media(video,"fid",info,Daily,
                               None,None,None,lambda p:Path(p))

    def test_orphan_english_source_after_crash_is_reprepared(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as t:
            video=Path(t)/"movie.mkv"
            video.write_bytes(b"fixture")
            work=Path(t)/"checkpoint"
            work.mkdir(mode=0o700)
            orphan=work/"source.en.srt"
            orphan.write_text("interrupted prepare",encoding="utf-8")
            orphan.chmod(0o600)
            cues=[{"number":1,"start":"00:00:00,000","end":"00:00:01,000",
                   "english":"Hi."}]
            engine=SimpleNamespace(MODEL_HASH="testhash")
            daily=SimpleNamespace(probe=lambda v:{"audio_en":True,"ja":False,
                                                  "embedded_en":0})
            small=SimpleNamespace(format_srt=lambda rows,lang:"fresh English SRT")
            mod=(None,engine,None,small,daily,None,lambda v:Path(v))
            row={"jellyfin_id":"real-id","path":str(video),"kind":"Movie"}
            with patch.object(ai,"saved_media",return_value=(
                    video,cues,"rawhash","same_file",{"mode":"embedded"})):
                _,got,m=ai.prepared_source(row,work,mod)
            self.assertEqual(got,cues)
            self.assertEqual(orphan.read_text(),"fresh English SRT")
            self.assertEqual(m["jellyfin_id"],"real-id")
            self.assertTrue((work/"manifest.json").is_file())

    def test_orphan_source_with_cue_checkpoint_must_hold(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as t:
            video=Path(t)/"movie.mkv"
            video.write_bytes(b"fixture")
            work=Path(t)/"checkpoint"
            work.mkdir(mode=0o700)
            orphan=work/"source.en.srt"
            orphan.write_text("orphan",encoding="utf-8")
            orphan.chmod(0o600)
            (work/"progress.sqlite3").write_bytes(b"checkpoint")
            mod=(None,SimpleNamespace(MODEL_HASH="test"),None,None,
                 None,None,lambda p:Path(p))
            with self.assertRaisesRegex(RuntimeError,"orphan_source_with_checkpoints"):
                ai.prepared_source({"jellyfin_id":"x","path":str(video)},work,mod)
            self.assertEqual(orphan.read_text(),"orphan")

    def test_source_routing_is_not_based_on_filename_only(self):
        self.assertNotIn("American Dad",ai.__doc__ or "")
        self.assertTrue(ai.ALLOWED_ACTIONS.issubset(ai.PLANNABLE_ACTIONS))


if __name__ == "__main__":
    unittest.main()
