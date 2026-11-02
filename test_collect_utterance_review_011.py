"""Read-only v011 collector regression; fake media and SRT only."""
from pathlib import Path
import hashlib
import io
import json
import tarfile
import tempfile
import unittest

from tools import collect_utterance_review_011 as collector


def srt(ja=False,second_ms='02'):
    one='こんにちは。' if ja else 'Hello.'
    two='こんばんは。' if ja else 'Good evening.'
    return (f'1\n00:00:00,000 --> 00:00:01,500\n{one}\n\n'
            f'2\n00:00:{second_ms},000 --> 00:00:04,000\n{two}\n').encode('utf8')


class Collector011(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root=Path(self.tmp.name)
        self.state=root/'state'
        self.folder=self.state/'episodes'/'S20E11'
        self.folder.mkdir(parents=True)
        self.en=self.folder/'source.en.srt'
        self.ja=self.folder/'pilot-v3.ja.srt'
        self.en.write_bytes(srt())
        self.ja.write_bytes(srt(True))
        self.video=root/'media'/'American Dad S20E11.mkv'
        self.video.parent.mkdir()
        self.video.write_bytes(b'fake')
        self.published=self.video.with_name(
            self.video.stem+'.Bruiser Utterance v3 Japanese.ja.srt')
        self.published.write_bytes(self.ja.read_bytes())
        self.report=self.folder/'quality-v3-abc.json'
        self.report.write_text(json.dumps({
            'schema':collector.SCHEMA,'episode':'S20E11','source_cues':2,
            'unit_count':1,'multi_cue_units':1,'grouped_cues':2,
            'first_pass_flags':{},'repaired_cues':0,'remaining_flags':{},
            'unresolved_ids':[]}))
        (self.state/'manifest.json').write_text(json.dumps({
            'schema':collector.SCHEMA,'episodes':[{
             'episode':'S20E11','source_path':str(self.en),
             'source_sha':hashlib.sha256(self.en.read_bytes()).hexdigest(),
             'video':str(self.video),'count':2}]}))

    def test_archive_exact_pairs_and_safe_index(self):
        out=io.BytesIO()
        collector.stream(self.state,out)
        with tarfile.open(fileobj=io.BytesIO(out.getvalue()),mode='r:gz') as t:
            self.assertIn('S20E11/source.en.srt',t.getnames())
            self.assertIn('S20E11/utterance.ja.srt',t.getnames())
            self.assertEqual(t.extractfile('S20E11/utterance.ja.srt').read(),
                             self.ja.read_bytes())
            meta=json.load(t.extractfile('INDEX.json'))
            self.assertNotIn(str(self.video.parent),str(meta))
            self.assertTrue(meta['episodes'][0]['published_verified_identical'])

    def test_bad_source_cannot_be_archived(self):
        self.en.write_bytes(srt().replace(b'Hello',b'Later'))
        with self.assertRaisesRegex(RuntimeError,'hash mismatch'):
            collector.collect(self.state)

    def test_timecode_drift_cannot_be_archived(self):
        self.ja.write_bytes(srt(True,second_ms='03'))
        self.published.write_bytes(self.ja.read_bytes())
        with self.assertRaisesRegex(RuntimeError,'drifted'):
            collector.collect(self.state)

    def test_published_track_must_match_draft(self):
        self.published.write_bytes(b'owner edited')
        with self.assertRaisesRegex(RuntimeError,'not identical'):
            collector.collect(self.state)

    def test_symlink_rejected(self):
        self.ja.unlink()
        self.ja.symlink_to(self.published)
        with self.assertRaisesRegex(RuntimeError,'missing/unsafe'):
            collector.collect(self.state)


if __name__=='__main__':
    unittest.main()
