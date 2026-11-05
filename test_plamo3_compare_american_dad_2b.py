"""No-network regression tests for the single real S19E13 PLaMo2B comparison.

Synthetic data only; no movie dialogue or actual model files checked into Git.
"""
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from tools import plamo3_compare_american_dad_2b as comp
from tools import plamo3_small_ab as small
from tools import plamo3_watch_american_dad as accepted


class PLaMo2BRealEpisodeTests(unittest.TestCase):
    def test_creator_protocol_is_unchanged_and_model_is_isolated(self):
        comp.self_test()
        self.assertEqual(comp.GPU_LAYERS,999)
        self.assertEqual(comp.CPU_THREADS,2)
        self.assertEqual(comp.real.HISTORY,2)
        self.assertEqual(comp.real.STOP,["<|plamo:tag|>", "<|plamo:bos|>"])
        self.assertNotEqual(comp.CHECKPOINT,accepted.CHECKPOINT)
        self.assertNotEqual(comp.WORK,accepted.WORK)

    def test_starts_2b_llama_server_two_cpu_threads_and_gpu_offload(self):
        class Proc:
            def poll(self):
                return None
        with tempfile.TemporaryDirectory() as folder:
            logger=Path(folder)/"server.log"
            with mock.patch.object(comp.small,"check_port"),\
                 mock.patch.object(comp.subprocess,"Popen",return_value=Proc()) as popen,\
                 mock.patch.object(comp.small,"json_request",return_value={"status":"ok"}):
                result=comp.new_model_server(Path("/bin/llama-server"),
                                             Path("/tmp/model.gguf"),logger,18885)
            self.assertIsInstance(result,Proc)
            command=popen.call_args.args[0]
            self.assertEqual(command[command.index("-ngl")+1],"999")
            self.assertEqual(command[command.index("-t")+1],"2")
            self.assertEqual(command[command.index("--host")+1],"127.0.0.1")

    def test_2b_history_uses_only_its_own_previous_translations(self):
        with tempfile.TemporaryDirectory() as d:
            db=sqlite3.connect(Path(d)/"cues.db")
            db.execute("""CREATE TABLE translation (
                idx INTEGER PRIMARY KEY, id INTEGER NOT NULL,
                start TEXT NOT NULL, end TEXT NOT NULL, english TEXT NOT NULL,
                japanese TEXT NOT NULL, status TEXT NOT NULL, seconds REAL NOT NULL)""")
            cues=small.samples()[:3]
            try:
                with mock.patch.object(comp.real,"request",
                        side_effect=[("これは一つ",{},"translated"),
                                     ("これは二つ",{},"translated"),
                                     ("これは三つ",{},"translated")]) as query:
                    output=comp.checkpoint_translate(db,cues,18885)
                self.assertEqual(len(output),3)
                self.assertEqual(query.call_args_list[0].args[2],[])
                self.assertEqual(query.call_args_list[1].args[2],
                                 [(cues[0]["english"],"これは一つ")])
                self.assertEqual(query.call_args_list[2].args[2],
                                 [(cues[0]["english"],"これは一つ"),
                                  (cues[1]["english"],"これは二つ")])
                self.assertEqual([r["number"] for r in output],
                                 [r["number"] for r in cues])
                self.assertEqual(len(comp.accepted.verify_checkpoints(db,cues)),3)
            finally:
                db.close()

    def test_private_pair_preserves_english_ids_and_both_models(self):
        en=small.samples()[:2]
        b8=[dict(r,japanese=j,status="translated",seconds=1)
            for r,j in zip(en,["日本語八","八号"])]
        b2=[dict(r,japanese=j,status="translated",seconds=2)
            for r,j in zip(en,["日本語二","二号"])]
        with tempfile.TemporaryDirectory() as d,\
             mock.patch.object(comp,"WORK",Path(d)):
            p=comp.export_pair(en,b8,b2,"a"*64,42)
            data=json.loads(p.read_text("utf-8"))
            self.assertEqual(len(data["entries"]),2)
            self.assertEqual(data["entries"][0]["english"],en[0]["english"])
            self.assertEqual(data["entries"][0]["plamo_8b"],"日本語八")
            self.assertEqual(data["entries"][0]["plamo_2b"],"日本語二")
            self.assertEqual(data["entries"][1]["start"],en[1]["start"])
            self.assertEqual(comp.export_pair(en,b8,b2,"a"*64,8000),p)
            mutated=[dict(b2[0],japanese="別の日本語"),b2[1]]
            with self.assertRaisesRegex(RuntimeError,
                                        "previous_private_review_data_changed"):
                comp.export_pair(en,b8,mutated,"a"*64,42)

    def test_pair_rejects_wrong_source_line(self):
        en=small.samples()[:2]
        b8=[dict(r,japanese="八",status="translated",seconds=1) for r in en]
        b2=[dict(r,japanese="二",status="translated",seconds=1) for r in en]
        b2[1]["start"]="10:00:00,000"
        with tempfile.TemporaryDirectory() as d,\
             mock.patch.object(comp,"WORK",Path(d)):
            with self.assertRaisesRegex(RuntimeError,
                                        "two_vs_eight_cue_alignment_failed"):
                comp.export_pair(en,b8,b2,"a"*64,42)

    def test_create_only_does_not_replace_an_existing_sidecar(self):
        with tempfile.TemporaryDirectory() as d:
            file=Path(d)/"PLaMo2B.ja.srt"
            comp.create_new(file,"日本語二".encode())
            self.assertEqual(file.read_text(),"日本語二")
            comp.create_new(file,"日本語二".encode())
            with self.assertRaisesRegex(RuntimeError,
                                        "existing_output_conflicts"):
                comp.create_new(file,"overwrite".encode())
            self.assertEqual(file.read_text(),"日本語二")

    def test_publishing_2b_never_overwrites_8b(self):
        with tempfile.TemporaryDirectory() as d:
            video=Path(d)/"American.Dad.S19E13.mkv"
            video.write_bytes(b"unchanged video")
            a=accepted.safe_dest(video)
            a.write_bytes(b"approved eight")
            stat=video.stat()
            m={"video_size":stat.st_size,"video_mtime_ns":stat.st_mtime_ns}
            h=hashlib.sha256(a.read_bytes()).hexdigest()
            v=comp.publish_alternative(video,m,h,"1\nJP two\n")
            self.assertIn("PLaMo2B",v.name)
            self.assertEqual(a.read_bytes(),b"approved eight")
            self.assertEqual(video.read_bytes(),b"unchanged video")
            with self.assertRaisesRegex(RuntimeError,"accepted_8b_track_changed"):
                comp.publish_alternative(video,m,"f"*64,"overwrite")
            self.assertEqual(v.read_text(),"1\nJP two\n")


if __name__=="__main__":
    unittest.main()
