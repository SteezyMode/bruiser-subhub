"""Offline guards for selective IASIP S12 E04/E05 repair (no real media)."""
from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock,patch

TOOLS=str(Path(__file__).resolve().parent/"tools")
sys.path.insert(0,TOOLS)
try:
    import repair_iasip_s12_overlap as repair
finally:
    sys.path.remove(TOOLS)


def episodes():
    return {
        "a"*32:{"kind":"Episode","series_title":repair.SERIES,
                "season":12,"episode":4,"jellyfin_id":"a"*32,
                "host_path":"/mnt/BigDisk/Video/Television/Episodic/IASIP/S12E04.mkv"},
        "b"*32:{"kind":"Episode","series_title":repair.SERIES,
                "season":12,"episode":5,"jellyfin_id":"b"*32,
                "host_path":"/mnt/BigDisk/Video/Television/Episodic/IASIP/S12E05.mkv"},
    }


class ScopeTests(unittest.TestCase):
    def test_exact_scope_detects_both_episodes(self):
        data=episodes()
        with patch.object(repair.stage,"read_inventory",return_value=data):
            found=repair.chosen_inventory()
        self.assertEqual(set(found),set(data))

    def test_rejects_nonunique_episode(self):
        data=episodes()
        data["c"*32]=dict(data["a"*32,jellyfin_id="c"*32)
        with patch.object(repair.stage,"read_inventory",return_value=data):
            with self.assertRaisesRegex(RuntimeError,"nonunique"):
                repair.chosen_inventory()

    def test_staged_repair_uses_existing_publisher_only(self):
        records=[("a"*32,"9062900","a"*64),("b"*32,"9790929","b"*64)]
        target=MagicMock()
        target.is_symlink.return_value=False
        target.exists.return_value=False
        target.is_file.return_value=True
        with patch.object(repair,"require_idle"),\
             patch.object(repair.autofill,"lock",return_value=40),\
             patch.object(repair.os,"close"),\
             patch.object(repair,"chosen_inventory",return_value=episodes()),\
             patch.object(repair.publisher,"stages",return_value=records),\
             patch.object(repair.publisher,"unique_titles",return_value={
                 "a"*32:[("9062900","a"*64)],
                 "b"*32:[("9790929","b"*64)]
             }),\
             patch.object(repair.publisher,"choose",return_value=(
                 "ready_ffsubsync",{},{"assessment":{"overlap_repaired_cues":15}})),\
             patch.object(repair.publisher,"publish_selected") as publish,\
             patch.object(repair.publisher,"mark_completed") as mark,\
             patch.object(repair.direct,"safe_media_path",return_value=Path("/video.mkv")) ,\
             patch.object(repair.direct,"video_target",return_value=target),\
             patch.object(repair,"COVERAGE",Path("/nonexistent/dashboard.py")):
            self.assertEqual(repair.repair_two(),0)
        self.assertEqual(publish.call_count,2)
        self.assertEqual(mark.call_count,2)

    def test_unsafe_candidate_is_held_not_published(self):
        records=[("a"*32,"9062900","a"*64),("b"*32,"9790929","b"*64)]
        target=MagicMock()
        target.is_symlink.return_value=False
        target.exists.return_value=False
        with patch.object(repair,"require_idle"),\
             patch.object(repair.autofill,"lock",return_value=41),\
             patch.object(repair.os,"close"),\
             patch.object(repair,"chosen_inventory",return_value=episodes()),\
             patch.object(repair.publisher,"stages",return_value=records),\
             patch.object(repair.publisher,"unique_titles",return_value={
                 "a"*32:[("9062900","a"*64)],
                 "b"*32:[("9790929","b"*64)]
             }),\
             patch.object(repair.publisher,"choose",side_effect=RuntimeError(
                 "overlap_repair_requires_unsafe_trim")) ,\
             patch.object(repair.publisher,"publish_selected") as publish,\
             patch.object(repair.publisher,"mark_completed") as mark,\
             patch.object(repair.direct,"safe_media_path",return_value=Path("/video.mkv")),\
             patch.object(repair.direct,"video_target",return_value=target),\
             patch.object(repair,"COVERAGE",Path("/nonexistent/dashboard.py")):
            self.assertEqual(repair.repair_two(),2)
        publish.assert_not_called()
        mark.assert_not_called()

    def test_dry_run_does_not_enter_repair(self):
        with patch.object(repair,"repair_two") as work:
            self.assertEqual(repair.main([]),0)
        work.assert_not_called()


if __name__=="__main__":
    unittest.main()
