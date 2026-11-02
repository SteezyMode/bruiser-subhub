"""Synthetic regression: read-only ContextSafe 010 EN/JA review archive."""
from pathlib import Path
import hashlib
import io
import json
import sys
import tarfile
import tempfile
import types
import unittest
from unittest.mock import patch

from tools import collect_contextsafe_review_010 as c


def fake_parser(data):
    import re
    chunks = re.split(r'\r?\n\s*\r?\n', data.decode('utf8').strip())
    out = []
    for chunk in chunks:
        lines = chunk.splitlines()
        def ms(value):
            h, m, s = value.split(':')
            sec, millis = s.split(',')
            return (int(h)*3600 + int(m)*60 + int(sec))*1000 + int(millis)
        a, b = (x.strip() for x in lines[1].split('-->'))
        out.append((int(lines[0]), lines[1], ms(a), ms(b), '\n'.join(lines[2:])))
    return out


def srt(value, shifted=False):
    start = '03' if shifted else '02'
    return (f'1\n00:00:00,000 --> 00:00:01,500\n{value}\n\n'
            f'2\n00:00:{start},000 --> 00:00:04,000\n{value}\n').encode('utf8')


class PrivateContextsafeReview(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.state = self.root / 'state'
        self.folder = self.state / 'episodes' / 'S19E07'
        self.folder.mkdir(parents=True)
        self.source = self.folder / 'source.en.srt'
        self.draft = self.folder / 'pilot-v2.ja.srt'
        self.en, self.ja = srt('Hello.'), srt('こんにちは。')
        self.source.write_bytes(self.en)
        self.draft.write_bytes(self.ja)
        video = self.root / 'media' / 'American.Dad.S19E07.mkv'
        video.parent.mkdir()
        self.target = video.with_name(video.stem + '.Bruiser ContextSafe v2 Japanese.ja.srt')
        self.target.write_bytes(self.ja)
        (self.state / 'manifest.json').write_text(json.dumps({
            'schema': c.SCHEMA, 'episodes': [{
                'episode': 'S19E07', 'source_path': str(self.source),
                'video': str(video), 'count': 2,
                'source_sha': hashlib.sha256(self.en).hexdigest()}]}))
        (self.folder / 'quality-v2-test.json').write_text(json.dumps({
            'episode':'S19E07', 'source_cues':2, 'first_pass_leak_flags':0,
            'first_pass_severe_density':0, 'repaired_cues':0,
            'unresolved_ids':[], 'remaining_leak_flags':0,
            'remaining_severe_density':0, 'warning_over_18_cps':0}))
        mocked = patch.dict(sys.modules, {
            'service': types.SimpleNamespace(parse_srt=fake_parser)})
        mocked.start()
        self.addCleanup(mocked.stop)

    def test_private_archive_and_no_media_paths_in_index(self):
        result = io.BytesIO()
        c.stream(self.state, result)
        with tarfile.open(fileobj=io.BytesIO(result.getvalue()), mode='r:gz') as t:
            self.assertEqual(set(t.getnames()), {
                'INDEX.json','S19E07/source.en.srt',
                'S19E07/contextsafe.ja.srt','S19E07/quality-v2-test.json'})
            self.assertEqual(t.extractfile('S19E07/source.en.srt').read(), self.en)
            idx = json.load(t.extractfile('INDEX.json'))
            self.assertTrue(idx['episodes'][0]['published_verified_identical'])
            self.assertNotIn(str(self.root / 'media'),str(idx))
        self.assertEqual(self.target.read_bytes(),self.ja)

    def test_source_tamper_rejected(self):
        self.source.write_bytes(srt('Tampered'))
        with self.assertRaisesRegex(RuntimeError,'SHA mismatch'):
            c.check_archive(self.state)

    def test_timing_drift_rejected(self):
        self.draft.write_bytes(srt('こんにちは。', shifted=True))
        self.target.write_bytes(self.draft.read_bytes())
        with self.assertRaisesRegex(RuntimeError,'timing drift'):
            c.check_archive(self.state)

    def test_published_drift_rejected(self):
        self.target.write_bytes(b'Changed after publication')
        with self.assertRaisesRegex(RuntimeError,'not identical'):
            c.check_archive(self.state)

    def test_missing_or_symlinked_srt_rejected(self):
        self.draft.unlink()
        with self.assertRaisesRegex(RuntimeError,'missing/unsafe'):
            c.check_archive(self.state)
        self.draft.symlink_to(self.target)
        with self.assertRaisesRegex(RuntimeError,'missing/unsafe'):
            c.check_archive(self.state)


if __name__ == '__main__':
    unittest.main()
