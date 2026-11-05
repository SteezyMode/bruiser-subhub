"""Retire known-published JA candidates without losing saved source provenance."""
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

TOOLS=str(Path(__file__).resolve().parent/"tools")
sys.path.insert(0,TOOLS)
try:
    import ja_first_publish_queue as queue
finally:
    sys.path.remove(TOOLS)


class RetiredPublicationTests(unittest.TestCase):
    def test_completed_items_drop_from_pending_but_remain_authenticated(self):
        with tempfile.TemporaryDirectory() as temp:
            db=Path(temp)/"stage.sqlite3"
            ident="a"*32
            pending="b"*32
            with sqlite3.connect(db) as con:
                con.execute("CREATE TABLE staged "
                            "(jellyfin_id TEXT,subtitle_id TEXT,sha256 TEXT,"
                            "status TEXT)")
                con.executemany(
                    "INSERT INTO staged VALUES (?,?,?,?)",
                    [(ident,"1234","0"*64,"staged"),
                     (ident,"1235","1"*64,"staged"),
                     (pending,"5678","2"*64,"staged")])
            with patch.object(queue.direct,"STAGE_DB",db):
                self.assertEqual(len(queue.stages()),3)
                queue.mark_completed(ident)
                self.assertEqual(len(queue.stages()),1)
                self.assertEqual(queue.stages()[0][0],pending)
                # Idempotent, preserve row content for verification.
                queue.mark_completed(ident)
                with sqlite3.connect(db) as con:
                    existing=con.execute(
                        "SELECT subtitle_id,status,sha256 FROM staged "
                        "WHERE jellyfin_id=? ORDER BY subtitle_id",(ident,)).fetchall()
                self.assertEqual(existing,[
                    ("1234","published","0"*64),
                    ("1235","published","1"*64)
                ])

    def test_invalid_identity_cannot_mutate_state(self):
        with self.assertRaisesRegex(RuntimeError,"invalid_completed_media_id"):
            queue.mark_completed("../../escape")


if __name__=="__main__":
    unittest.main()
