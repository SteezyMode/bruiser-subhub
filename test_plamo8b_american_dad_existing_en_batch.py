"""No real video/subtitle text or model weights. Verify batch safety gates."""
import argparse
from pathlib import Path
import tempfile
from types import SimpleNamespace
from unittest import TestCase, main, mock

from tools import plamo8b_american_dad_existing_en_batch as batch
from tools import plamo3_watch_american_dad as engine


class AmericanDadExistingEnglishBatchTests(TestCase):
    def test_unchanged_model_protocol_and_scoped_roger_fix(self):
        batch.self_test()
        self.assertEqual(batch.GPU_LAYERS,28)
        self.assertEqual(batch.CPU_THREADS,2)
        self.assertEqual(batch.MODEL_FILENAME,"plamo-3-translate-8b-Q4_K_M.gguf")
        self.assertEqual(batch.safe_roger_name("Roger, this is terrible",
                     "了解、これはひどい"),"ロジャー、これはひどい")
        self.assertEqual(batch.safe_roger_name("- Roger!","- 了解！"),"- ロジャー！")
        self.assertEqual(batch.safe_roger_name("Roger that.","了解。"),"了解。")
        self.assertEqual(batch.safe_roger_name("I roger that.","了解。"),"了解。")
        self.assertEqual(batch.safe_roger_name("Roger,","了解しました"),"了解しました")
        self.assertEqual(batch.safe_roger_name("Roger, you know","ロジャーだよ"),
                         "ロジャーだよ")

    def test_inventory_prefers_20_then_21_then_19_and_skips_japanese(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)
            files=[p/"American.Dad.S19E11.mkv",
                   p/"American.Dad.S20E01.mkv",
                   p/"American.Dad.S21E02.mkv",
                   p/"American.Dad.S08E02.mkv",
                   p/"American.Dad.S19E13.mkv",
                   p/"American.Dad.S01E01.mkv"]
            for v in files:
                v.write_bytes(b"harmless media fixture")
            daily=SimpleNamespace(
                video_files=lambda _:iter(files),
                probe=lambda v:{"ja":v.name.endswith("S19E13.mkv"),
                    "audio_en":True,"embedded_en":0},
                already_ja=lambda _:False,
                english_srt=lambda _:None
            )
            with mock.patch.object(batch,"MEDIA",p):
                work,ja,missing,errors=batch.scan(daily)
            self.assertEqual([x[0] for x in work],
                ["S20E01","S21E02","S19E11","S08E02"])
            self.assertEqual(ja,["S19E13"])
            self.assertEqual(missing,[])
            self.assertEqual(errors,[])

    def test_skip_when_no_english_text_or_audio(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)
            a=p/"American.Dad.S20E01.mkv"
            b=p/"American.Dad.S20E02.mkv"
            a.write_bytes(b"x"); b.write_bytes(b"x")
            daily=SimpleNamespace(
                video_files=lambda _:iter((a,b)),
                probe=lambda v:{"ja":False,
                    "audio_en":v==b,
                    "embedded_en":None},
                already_ja=lambda _:False,
                english_srt=lambda v:Path("/tmp/actual.en.srt") if v==a else None,
            )
            with mock.patch.object(batch,"MEDIA",p):
                work,ja,missing,errors=batch.scan(daily)
            self.assertEqual(work,[])
            self.assertEqual(missing,["S20E01","S20E02"])

    def test_state_per_episode_is_restored_even_after_error(self):
        before=(engine.WORK,engine.CHECKPOINT,engine.SOURCE,engine.MANIFEST)
        with tempfile.TemporaryDirectory() as d:
            with mock.patch.object(batch,"STATE",Path(d)):
                with self.assertRaisesRegex(ValueError,"test unwind"):
                    with batch.separate_episode(
                            Path("/tv/American.Dad.S20E01.mkv"),"S20E01"):
                        self.assertNotEqual(engine.WORK,before[0])
                        self.assertTrue(str(engine.WORK).startswith(d))
                        raise ValueError("test unwind")
        self.assertEqual((engine.WORK,engine.CHECKPOINT,engine.SOURCE,engine.MANIFEST),
                         before)

    def test_cooling_gate_halts_hot_cpu_and_resumes_after_cooling(self):
        temps=[(81.,65.),(77.,64.),(72.,64.)]
        with mock.patch.object(batch,"temperatures",side_effect=temps),\
             mock.patch.object(batch.time,"sleep") as pause:
            batch.thermal_gate()
        self.assertEqual(pause.call_count,2)

    def test_unreadable_temperature_fails_closed(self):
        with mock.patch.object(batch,"temperatures",side_effect=RuntimeError("NO_SENSOR")):
            with self.assertRaisesRegex(RuntimeError,"NO_SENSOR"):
                batch.thermal_gate()

    def test_batch_server_two_cpu_threads_and_no_gpu_cap_change(self):
        class Proc:
            def poll(self):
                return None
        with tempfile.TemporaryDirectory() as d:
            log=Path(d)/"llama.log"
            with mock.patch.object(batch.small,"check_port"),\
                 mock.patch.object(batch,"gpu_state",return_value=(60.,5200)),\
                 mock.patch.object(batch.subprocess,"Popen",return_value=Proc()) as popen,\
                 mock.patch.object(batch.small,"json_request",return_value={"status":"ok"}):
                batch.start_cool_server(Path("/bin/llama-server"),
                       Path("/model.gguf"),18886,28,log)
            argv=popen.call_args.args[0]
            self.assertEqual(argv[argv.index("-t")+1],"2")
            self.assertEqual(argv[argv.index("-ngl")+1],"28")
            self.assertEqual(argv[argv.index("--host")+1],"127.0.0.1")
            self.assertNotIn("nvidia-smi",argv)


if __name__=="__main__":
    main()
