"""Prove real SQLite rows reach the explicitly named legacy JSON adapter.

These tests avoid Ollama but exercise the actual translation adapter and source
ID mapping, unlike the mocked translate_window integration tests.
"""
import sys
import types
import unittest
from unittest.mock import patch
from pathlib import Path
import tempfile
import service as s


SOURCE = (
    '1\n00:00:00,100 --> 00:00:01,100\nStart.\n\n'
    '2\n00:00:01,200 --> 00:00:02,100\n\n'
    '3\n00:00:02,200 --> 00:00:03,200\nDo not leave!\n\n'
    '4\n00:00:03,300 --> 00:00:04,300\nWhat happened?\n'
).encode('utf-8')


class BatchRegressionTests(unittest.TestCase):
    def make_rows(self):
        tmp=tempfile.TemporaryDirectory()
        db=s.Store(Path(tmp.name))
        db.add('film-test',Path(tmp.name)/'film.mkv',SOURCE,'eng')
        return tmp,db,db.rows('film-test')

    def test_clip_uses_real_sqlite_fields_not_positional_columns(self):
        temp,st,rows=self.make_rows()
        try:
            clip=s.render_clip(rows[1:])
            self.assertNotIn(b'film-test',clip)
            self.assertNotIn(b'3200',clip)
            parsed=s.parse_srt(clip)
            self.assertEqual([v[0] for v in parsed],[1,2])
            self.assertEqual([v[4] for v in parsed],['Do not leave!','What happened?'])
            self.assertEqual([v[1] for v in parsed],
                ['00:00:02,200 --> 00:00:03,200','00:00:03,300 --> 00:00:04,300'])
        finally:st.cn.close();temp.cleanup()

    def test_adapter_maps_local_prompt_ids_back_to_true_source_ids(self):
        temp,st,rows=self.make_rows()
        fake=types.ModuleType('bruiser_auto')
        def parse_file(path):
            parsed=s.parse_srt(Path(path).read_bytes())
            return [types.SimpleNamespace(id=v[0],text=v[4]) for v in parsed]
        fake.parse_srt=parse_file
        def build(cues,start,end,memory):
            self.assertEqual([(c.id,c.text) for c in cues],
                             [(1,'Do not leave!'),(2,'What happened?')])
            self.assertEqual(memory,'Approved memory')
            return ('system','payload')
        fake.build_prompt=build
        def call(url,model,system,payload,ids,seconds):
            self.assertEqual(ids,[1,2])
            self.assertEqual(system,'system')
            self.assertEqual(payload,'payload')
            return {1:'行かないで！',2:'何があった？'}
        fake.call_ollama=call
        fake.preserve_tags=lambda english,japanese:japanese
        try:
            with patch.dict(sys.modules, {'bruiser_auto':fake}):
                got=s.legacy_json_translation_call(Path(temp.name),rows[1:],'Approved memory')
            self.assertEqual(got,{'3':'行かないで！','4':'何があった？'})
        finally:st.cn.close();temp.cleanup()

    def test_batch_does_not_write_any_translation_checkpoint(self):
        temp,st,rows=self.make_rows()
        try:
            before=[x['japanese'] for x in rows]
            s.render_clip(rows)
            self.assertEqual([x['japanese'] for x in st.rows('film-test')],before)
        finally:st.cn.close();temp.cleanup()


if __name__=='__main__':unittest.main()
