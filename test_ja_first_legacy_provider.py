"""Legacy OpenSubtitles staging provenance stays readable across the whole library.

Records acquired before provider tags existed must authenticate against the
saved source candidate; don't mutate existing databases or bypass identity.
"""
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

TOOLS = str(Path(__file__).resolve().parent / "tools")
sys.path.insert(0, TOOLS)
try:
    import ja_first_publish_staged as publisher
finally:
    sys.path.remove(TOOLS)


class LegacyOpenSubtitlesMetadataTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.stage = self.root / "staged"
        self.stage.mkdir(mode=0o700)
        self.sid = "8498567"
        self.jid = "a" * 32
        self.bytes = b"1\n00:00:00,000 --> 00:00:01,000\n\xe3\x81\x93\xe3\x82\x93\xe3\x81\xab\xe3\x81\xa1\xe3\x81\xaf\n"
        self.digest = hashlib.sha256(self.bytes).hexdigest()
        self.track = self.stage / (self.jid + ".opensubtitles." + self.sid + ".ja.srt")
        self.track.write_bytes(self.bytes)
        self.track.chmod(0o600)
        self.stage_db = self.root / "staging.sqlite3"
        self.search_db = self.root / "search.sqlite3"
        self.metrics = {"format": "srt", "bytes": len(self.bytes),
                        "cues": 1, "video_seconds": 1200}
        with sqlite3.connect(self.stage_db) as conn:
            conn.execute("""CREATE TABLE staged (
                jellyfin_id TEXT, subtitle_id TEXT, host_path TEXT,
                sha256 TEXT, status TEXT, metrics_json TEXT
            )""")
            conn.execute("INSERT INTO staged VALUES (?,?,?,?,?,?)",
                         (self.jid, self.sid, str(self.track),
                          self.digest, "staged", json.dumps(self.metrics)))
        self.stage_db.chmod(0o600)
        self.candidate = {
            "provider": "opensubtitles", "subtitle_id": self.sid,
            "language": "ja", "filename": "Example.Show.S09E04.ja.srt",
            "matches": ["series", "season", "episode"]
        }
        self.row = {
            "kind": "Episode", "series_title": "Example Show",
            "season": 9, "episode": 4, "series_imdb_id": "tt0000123",
            "jellyfin_id": self.jid
        }
        with sqlite3.connect(self.search_db) as conn:
            conn.execute("CREATE TABLE searches (jellyfin_id TEXT, results_json TEXT)")
            conn.execute("INSERT INTO searches VALUES (?,?)",
                         (self.jid, json.dumps({"candidates": [self.candidate]})))
        self.search_db.chmod(0o600)
        for target, value in (("STAGE_DB", self.stage_db),
                              ("STAGED", self.stage),
                              ("SEARCH_DB", self.search_db)):
            mock = patch.object(publisher, target, value)
            mock.start()
            self.addCleanup(mock.stop)

    def test_legacy_record_with_missing_provider_is_authenticated(self):
        stage, content, metrics = publisher.read_staging(self.jid, self.sid)
        self.assertEqual(stage, self.track)
        self.assertEqual(content, self.bytes)
        self.assertNotIn("provider", metrics)
        publisher.verify_search_identity(self.row, self.jid, self.sid)

    def test_legacy_record_does_not_skip_saved_identity(self):
        wrong = dict(self.row, episode=5)
        with self.assertRaisesRegex(RuntimeError, "candidate_not_safely_identified"):
            publisher.verify_search_identity(wrong, self.jid, self.sid)

    def test_explicit_incorrect_provider_is_still_rejected(self):
        with sqlite3.connect(self.stage_db) as conn:
            conn.execute("UPDATE staged SET metrics_json=?",
                         (json.dumps({**self.metrics, "provider":"subdl"}),))
        with self.assertRaisesRegex(RuntimeError, "staging_provenance_provider_mismatch"):
            publisher.read_staging(self.jid, self.sid)


if __name__ == "__main__":
    unittest.main()
