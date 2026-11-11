"""Ensure explicit single-item publication cannot process unrelated stage rows."""
import contextlib
import io
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

toolpath=str(Path(__file__).resolve().parent/"tools")
added=toolpath not in sys.path
if added:sys.path.insert(0,toolpath)
try:
    import ja_first_publish_queue as queue
finally:
    if added:sys.path.remove(toolpath)


class ItemScopedPublisher(unittest.TestCase):
    def test_exact_jellyfin_id_is_only_title_in_dry_run(self):
        chosen="a"*32
        other="b"*32
        rows=[(other,"1134","0"*64),(chosen,"11947715","1"*64)]
        with patch.object(sys,"argv",["ja_first_publish_queue.py",
                                       "--jellyfin-id",chosen,"--limit","1"]), \
             patch.object(queue,"stages",return_value=rows), \
             patch.object(queue,"choose",return_value=(
                 "ready_alass",{"title":"One Episode","kind":"Episode"},{})) as take, \
             patch.object(queue,"publish_selected") as publish, \
             contextlib.redirect_stdout(io.StringIO()) as output:
            queue.main()
        take.assert_called_once_with(chosen,[("11947715","1"*64)])
        publish.assert_not_called()
        self.assertIn("matching_stage_rows: 1",output.getvalue())

    def test_invalid_item_id_does_not_scan_stages(self):
        with patch.object(sys,"argv",["ja_first_publish_queue.py",
                                       "--jellyfin-id","../bad"]), \
             patch.object(queue,"stages") as get, \
             contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                queue.main()
        get.assert_not_called()

    def test_no_exact_match_does_not_choose_an_unrelated_title(self):
        with patch.object(sys,"argv",["ja_first_publish_queue.py",
                                       "--jellyfin-id","a"*32]), \
             patch.object(queue,"stages",return_value=[("b"*32,"1234","x")]), \
             patch.object(queue,"choose") as choose, \
             contextlib.redirect_stdout(io.StringIO()):
            queue.main()
        choose.assert_not_called()


if __name__=="__main__":
    unittest.main()
