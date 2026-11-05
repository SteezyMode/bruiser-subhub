"""Regression for a Jellyfin catalog refresh after source-first JA publication.

A sidecar already published by SubHub becomes 'existing_japanese_subtitle'
in the new catalog. This must retire its old staged queue record, but NEVER
authorize replacement or accept an unrelated/mutated Japanese subtitle.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

TOOLS = str(Path(__file__).resolve().parent / "tools")
sys.path.insert(0, TOOLS)
try:
    import ja_first_publish_queue as queue
    import ja_first_publish_staged as gate
finally:
    sys.path.remove(TOOLS)


class RefreshedCatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.stage = self.root / "staged"
        self.stage.mkdir(mode=0o700)
        self.jid = "a" * 32
        self.sid = "12345"
        self.raw = (
            "1\n00:00:03,000 --> 00:00:05,000\n日本語の字幕\n"
        ).encode("utf8")
        self.digest = hashlib.sha256(self.raw).hexdigest()
        self.video = self.root / "Example.mkv"
        self.video.write_bytes(b"not an actual video; file identity fixture")
        self.sidecar = self.root / "Example.ja.srt"
        self.source = self.stage / (
            self.jid + ".opensubtitles." + self.sid + ".ja.srt"
        )
        self.source.write_bytes(self.raw)
        self.source.chmod(0o600)
        self.db = self.root / "japanese-stage.sqlite3"
        with sqlite3.connect(self.db) as db:
            db.execute("""CREATE TABLE staged (
                jellyfin_id TEXT, subtitle_id TEXT, host_path TEXT,
                sha256 TEXT, staged_at INTEGER, status TEXT, metrics_json TEXT
            )""")
            db.execute("INSERT INTO staged VALUES (?,?,?,?,?,?,?)",
                       (self.jid, self.sid, str(self.source), self.digest,
                        10, "staged", json.dumps({
                            "format": "srt", "bytes": len(self.raw)
                        })))
        self.db.chmod(0o600)
        self.status = "existing_japanese_subtitle"
        self.write_manifest()
        patches = [
            patch.object(gate, "ROOT", self.root),
            patch.object(gate, "STAGED", self.stage),
            patch.object(gate, "STAGE_DB", self.db),
            patch.object(gate, "safe_media_path", side_effect=lambda p: Path(p)),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def write_manifest(self):
        manifest = self.root / "ja-intake-20261105T000000Z.json"
        manifest.write_text(json.dumps({
            "schema": 1,
            "items": [{
                "jellyfin_id": self.jid,
                "kind": "Movie",
                "title": "Example",
                "year": 2000,
                "host_path": str(self.video),
                "status": self.status,
            }],
        }))
        manifest.chmod(0o600)

    def test_existing_identity_allowed_for_recognition_only(self):
        with self.assertRaisesRegex(RuntimeError, "no_longer_eligible"):
            gate.read_inventory(self.jid)
        self.assertEqual(gate.read_inventory(
            self.jid, allow_existing_ja=True)["status"],
            "existing_japanese_subtitle")
        self.assertEqual(queue.stages(), [(self.jid, self.sid, self.digest)])

    def test_known_original_published_before_refresh_is_retired(self):
        self.sidecar.write_bytes(self.raw)
        kind, row, _ = queue.choose(self.jid, [(self.sid, self.digest)])
        self.assertEqual(kind, "published_original")
        self.assertEqual(row["status"], "existing_japanese_subtitle")
        queue.mark_completed(self.jid)
        self.assertEqual(queue.stages(), [])
        _, preserved, _ = gate.read_staging(self.jid, self.sid)
        self.assertEqual(preserved, self.raw)
        self.assertEqual(self.sidecar.read_bytes(), self.raw)

    def test_unrelated_sidecar_can_never_be_retired_or_overwritten(self):
        self.sidecar.write_bytes(b"Different user-edited Japanese subtitle")
        with self.assertRaisesRegex(RuntimeError, "not_matching_saved_provenance"):
            queue.choose(self.jid, [(self.sid, self.digest)])
        self.assertEqual(len(queue.stages()), 1)

    def test_refreshed_status_never_allows_new_publication(self):
        # An existing JA file elsewhere may cause the refresh to mark this
        # episode ineligible. No canonical sidecar => not yet published by us.
        kind, row, _ = None, None, None
        with self.assertRaisesRegex(RuntimeError, "no_longer_eligible"):
            gate.preflight(self.jid, self.sid)
        self.assertEqual(len(queue.stages()), 1)

    def test_unrelated_catalog_status_not_accepted_for_retirement(self):
        self.status = "review_missing_path"
        self.write_manifest()
        self.sidecar.write_bytes(self.raw)
        with self.assertRaisesRegex(RuntimeError, "no_longer_eligible"):
            queue.choose(self.jid, [(self.sid, self.digest)])
        self.assertEqual(len(queue.stages()), 1)


if __name__ == "__main__":
    unittest.main()
