"""Synthetic tests for read-only inspection of v012 failed raw replies."""
import io
import json
from pathlib import Path
import subprocess
import tarfile
import unittest
from unittest.mock import patch

from tools import collect_formatlab_failures_012 as forensic
from tools import utterance_formatlab_012 as lab
from test_utterance_formatlab_012 import Lab012


class Forensics012(unittest.TestCase):
    def setUp(self):
        self.fixture=Lab012('test_malformed_numbered_lines_and_cue_mapping_are_blocked')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def incomplete(self):
        return forensic.collect(
            self.fixture.state,self.fixture.original_state,self.fixture.profile)

    def bad_model(self,msg,mode):
        self.fixture.calls.append((mode,'deliberate-malformed'))
        if mode=='json':
            return {
                'content':'{"1":"日本語です。","1":"繰り返し。"}',
                'done_reason':'length','eval_count':450,
                'prompt_eval_count':100,'total_duration_ns':10000}
        return {'content':'これは日本語ですが、番号がありません。',
                'done_reason':'stop','eval_count':21,
                'prompt_eval_count':100,'total_duration_ns':10000}

    def populate(self):
        return self.fixture.experiment(ask=self.bad_model)

    def test_no_selection_or_incomplete_data_are_refused(self):
        with self.assertRaisesRegex(RuntimeError,'selection missing'):
            self.incomplete()
        self.fixture.sample()
        with self.assertRaisesRegex(RuntimeError,'not yet complete'):
            self.incomplete()

    def test_failed_raw_output_is_private_and_source_is_untouched(self):
        summary=self.populate()
        self.assertEqual(summary['completed_calls'],48)
        before=dict(self.fixture.before)
        data=self.incomplete()
        self.assertEqual(data['schema'],forensic.SCHEMA)
        self.assertEqual(data['total_failure_responses'],48)
        self.assertEqual(data['failure_categories'],{
            'json_length_cap':24,'lines_id_mapping_or_count':24})
        self.assertEqual(len(self.fixture.calls),48)
        records=data['records']
        self.assertEqual(records[0]['mode'],'json')
        self.assertEqual(records[0]['output_tokens'],450)
        self.assertEqual(records[1]['mode'],'lines')
        self.assertEqual(records[1]['shape_observations']['numbered_lines'],0)
        self.assertEqual(records[1]['shape_observations']['other_lines'],1)
        self.assertEqual(records[1]['raw_model_output'],
                         'これは日本語ですが、番号がありません。')
        self.assertEqual(before,{
            str(p):p.read_bytes() for p in self.fixture.original_state.rglob('*')
            if p.is_file()})
        self.assertEqual(list(self.fixture.state.rglob('*.srt')),[])
        # Merely inspecting saved responses cannot repeat any model call.
        self.assertEqual(len(self.fixture.calls),48)

    def test_private_archive_is_valid_and_not_a_public_sidecar(self):
        self.populate()
        buffer=io.BytesIO()
        with patch.object(lab,'model_call',side_effect=AssertionError(
                'Forensic reads must never call Ollama')):
            forensic.export(self.fixture.state,self.fixture.original_state,
                            self.fixture.profile,buffer)
        with tarfile.open(fileobj=io.BytesIO(buffer.getvalue()),mode='r:gz') as f:
            self.assertEqual(f.getnames(),[
                'PRIVATE_formatlab_012_failed_model_responses.json'])
            data=json.load(f.extractfile(f.getnames()[0]))
        self.assertEqual(data['total_failure_responses'],48)
        self.assertNotIn(str(self.fixture.original_state),str(data))
        self.assertEqual(list(self.fixture.state.rglob('*.srt')),[])

    def test_shape_counts_include_exact_expected_ids_and_json_metadata(self):
        x=forensic.classify_shape('10 | 日本語です。\n11 | 残りの部分です。',
                                  [10,11],'lines')
        self.assertTrue(x['exact_requested_numbered_ids'])
        self.assertEqual(x['numbered_ids'],['10','11'])
        x=forensic.classify_shape('10 | 日本語です。', [10,11],'lines')
        self.assertFalse(x['exact_requested_numbered_ids'])
        x=forensic.classify_shape('{"10":"日本語","11":"訳文"}',[10,11],'json')
        self.assertTrue(x['json_valid_syntax'])
        self.assertTrue(x['json_keys_exact'])
        x=forensic.classify_shape('{"10":',[10,11],'json')
        self.assertFalse(x['json_valid_syntax'])

    def test_cannot_export_if_source_sha_changes(self):
        self.populate()
        source=Path(self.fixture.entries['S19E10']['source_path'])
        source.write_bytes(source.read_bytes().replace(
            b'the new plan',b'new plan now'))
        with self.assertRaisesRegex(RuntimeError,'source hash mismatch'):
            self.incomplete()

    def test_host_command_is_read_only(self):
        wrapper=Path(__file__).resolve().parent/'tools/collect_formatlab_failures_012.sh'
        syntax=subprocess.run(['bash','-n',str(wrapper)],
                              capture_output=True,text=True)
        self.assertEqual(syntax.returncode,0,syntax.stderr)
        data=wrapper.read_text()
        self.assertIn('ssh "$HOST" '+"'python3 -'",data)
        self.assertNotIn('scp ',data)
        self.assertNotIn('docker restart',data)
        self.assertNotIn('systemctl',data)


if __name__=='__main__':
    unittest.main()
