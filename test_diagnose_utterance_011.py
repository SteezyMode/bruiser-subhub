"""Offline tests for private, read-only frozen v011 failure diagnostics."""
from pathlib import Path
import hashlib
import json
import subprocess
import tempfile
import unittest

import service
from tools import semantic_groups_011 as groups
from tools import diagnose_utterance_011 as diag


def srt():
    def tm(s):
        return '00:00:%02d,000'%s
    words=[
       'The first caption is complete.',
       'But this thought continues',
       'to the next subtitle.',
       'One complete thought.',
       'Another complete thought.',
       'Final complete thought.',
    ]
    return ('\n\n'.join(
        str(i+1)+'\n'+tm(i*2)+' --> '+tm(i*2+1)+'\n'+v
        for i,v in enumerate(words))+'\n').encode('utf8')


class Diagnostic011(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base=Path(self.tmp.name)
        self.state=base/'state'
        self.episode='S19E10'
        self.folder=self.state/'episodes'/self.episode
        self.folder.mkdir(parents=True)
        self.source=self.folder/'source.en.srt'
        self.source.write_bytes(srt())
        self.rows=service.parse_srt(srt())
        self.groups=groups.plan(self.rows)
        self.code=base/'original-v011-code'
        self.code.mkdir()
        paths=('american_dad_utterance_011.py','semantic_groups_011.py','subtitle_quality_010.py')
        for i,name in enumerate(paths):
            (self.code/name).write_bytes(bytes([65+i])*20)
        self.fingerprint=hashlib.sha256(b''.join(
            (self.code/x).read_bytes() for x in paths)).hexdigest()
        self.entry={'episode':self.episode,'source_path':str(self.source),
                    'source_sha':hashlib.sha256(srt()).hexdigest(),
                    'model_id':'known-model','count':len(self.rows)}
        (self.state/'manifest.json').write_text(json.dumps({
            'schema':diag.SCHEMA,'pipeline_sha':self.fingerprint,
            'episodes':[self.entry]}))
        # Ensure at least three independent units in test fixture.
        self.assertGreaterEqual(len(self.groups),3)
        self.good=self.groups[0]
        self.bad=self.groups[1]
        self.write_checkpoint(self.good)
        self.write_attempt(self.bad,1,'ValueError: Incomplete/extra keys in grouped translation')
        self.write_attempt(self.bad,2,'JSONDecodeError: Expecting value')
        self.write_attempt(self.bad,3,'ValueError: Invalid Japanese or speaker-turn structure')

    def name(self,unit):
        return '%05d-%05d'%(unit[0][0],unit[-1][0])

    def write_checkpoint(self,unit):
        folder=self.folder/'units'
        folder.mkdir(exist_ok=True)
        data={'schema':diag.SCHEMA,
              'source_sha':self.entry['source_sha'],
              'unit_sha':groups.unit_sha(unit),
              'ids':[r[0] for r in unit],
              'pipeline_sha':self.fingerprint,
              'model_id':'known-model',
              'translations':{str(r[0]):'短い日本語です。' for r in unit}}
        (folder/(self.name(unit)+'.json')).write_text(
            json.dumps(data,ensure_ascii=False))

    def write_attempt(self,unit,n,error):
        folder=self.folder/'attempts'
        folder.mkdir(exist_ok=True)
        (folder/(self.name(unit)+'-'+str(n)+'.json')).write_text(
            json.dumps({'ids':[r[0] for r in unit],'error':error}))

    def examine(self):
        return diag.diagnose(self.state,self.code,service.parse_srt,
                             groups.plan,groups.unit_sha)

    def test_recovers_grounded_numbers_and_private_categories(self):
        before=sorted(str(p) for p in self.state.rglob('*'))
        result=self.examine()
        row=result['episodes'][0]
        self.assertTrue(result['frozen_runner_fingerprint_ok'])
        self.assertEqual(row['accepted_cues'],len(self.good))
        self.assertEqual(row['failed_units_with_records'],1)
        self.assertEqual(row['exhausted_units'],1)
        self.assertEqual(row['never_attempted_units'],len(self.groups)-2)
        self.assertEqual(row['unaccepted_cues'],len(self.rows)-len(self.good))
        self.assertEqual(row['last_error_by_failed_unit'],
                         {'invalid_ja_or_speakers':1})
        self.assertEqual(row['attempt_errors_by_category']['group_keys_incorrect'],1)
        self.assertEqual(row['attempt_errors_by_category']['invalid_group_json'],1)
        self.assertNotIn('But this thought',str(result))
        self.assertNotIn(str(self.folder),str(result))
        self.assertEqual(before,sorted(str(p) for p in self.state.rglob('*')))

    def test_rejects_tampered_source(self):
        self.source.write_bytes(srt().replace(b'The first',b'The other'))
        with self.assertRaisesRegex(RuntimeError,'source has changed'):
            self.examine()

    def test_rejects_incompatible_checkpoint(self):
        path=self.folder/'units'/(self.name(self.good)+'.json')
        data=json.loads(path.read_text())
        data['unit_sha']='bad'
        path.write_text(json.dumps(data))
        with self.assertRaisesRegex(RuntimeError,'Incompatible'):
            self.examine()

    def test_rejects_source_symlink_and_code_modification(self):
        self.source.unlink()
        self.source.symlink_to(self.code/'american_dad_utterance_011.py')
        with self.assertRaises(RuntimeError):
            self.examine()
        self.source.unlink()
        self.source.write_bytes(srt())
        (self.code/'american_dad_utterance_011.py').write_bytes(b'changed')
        with self.assertRaisesRegex(RuntimeError,'fingerprint changed'):
            self.examine()

    def test_unrecognized_error_cannot_leak_private_dialogue(self):
        self.assertEqual(diag.failure_category('ValueError: Secret English line from video'),
                         'other_ValueError')
        self.assertEqual(diag.failure_category('Not a useful recognizable exception'),
                         'other')
        self.assertEqual(diag.failure_category('RuntimeError: Output length cap'),
                         'model_length_cap')

    def test_shell_wrapper_only_reads_host(self):
        path=Path(__file__).resolve().parent/'tools/diagnose_utterance_011.sh'
        run=subprocess.run(['bash','-n',str(path)],capture_output=True,text=True)
        self.assertEqual(run.returncode,0,run.stderr)
        content=path.read_text()
        self.assertIn("ssh \"$HOST\" 'python3 -'",content)
        self.assertNotIn('scp ',content)
        self.assertNotIn('docker restart',content)
        self.assertNotIn('systemctl',content)


if __name__=='__main__':
    unittest.main()
