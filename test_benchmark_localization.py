"""Private localization A/B helper uses read-only checkpoints and a fake model."""
import json
from pathlib import Path
import tempfile
import unittest

import service as s
from tools import benchmark_localization as b


class BenchmarkTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.base=Path(self.tmp.name)
        self.root=self.base/'state'
        db=s.Store(self.root)
        source=('\n\n'.join(
            f"{i}\n00:00:{i:02d},000 --> 00:00:{i+1:02d},000\n"
            f"Fake dialogue {i}."
            for i in range(1,13))+'\n').encode()
        db.add('fake-movie',self.base/'movie.mkv',source,'eng')
        db.record_japanese('fake-movie',{'2':'前の字幕。','5':'古い字幕。'})
        db.state('fake-movie','translated')
        db.cn.close()

    def tearDown(self):
        self.tmp.cleanup()

    def test_select_nonoverlapping_real_source_windows(self):
        _,rows=b.get_rows(self.root,'fake-movie')
        groups=b.windows(rows,[2,4,10],size=4)
        self.assertEqual(len(groups),2)
        self.assertEqual([r['cue_id'] for r in groups[0]],[1,2,3,4])
        self.assertEqual([r['cue_id'] for r in groups[1]],[8,9,10,11])
        with self.assertRaisesRegex(ValueError,'Unknown selected cue'):
            b.windows(rows,[50],size=4)

    def test_compare_calls_only_opt_in_style_and_never_writes_checkpoints(self):
        captured=[]
        def fake_call(base,rows,memory,style):
            self.assertEqual(style,'natural_8')
            captured.append([r['cue_id'] for r in rows])
            return {str(r['cue_id']):'冗談じゃないぞ！' for r in rows}
        before=(self.root/'jobs.sqlite3').stat().st_size
        sample=b.compare(self.base,self.root,'fake-movie',[2,10],size=4,call=fake_call)
        self.assertEqual(len(sample['entries']),8)
        self.assertEqual(len(captured),2)
        self.assertEqual(len(sample['windows']),2)
        self.assertEqual(sample['entries'][1]['existing_japanese'],'前の字幕。')
        self.assertTrue(all(r['candidate_japanese']=='冗談じゃないぞ！' for r in sample['entries']))
        _,after=b.get_rows(self.root,'fake-movie')
        self.assertEqual(after[1]['japanese'],'前の字幕。')
        self.assertEqual((self.root/'jobs.sqlite3').stat().st_size,before)

    def test_private_output_refuses_overwrite(self):
        out=self.base/'private.json'
        b.save_private(out,{'entries':[{'english':'private line'}]})
        self.assertEqual(json.loads(out.read_text())['entries'][0]['english'],'private line')
        with self.assertRaises(FileExistsError):
            b.save_private(out,{'different':'content'})

    def test_translator_error_is_recorded_without_touching_db(self):
        def fail(*args,**kwargs):raise ValueError('Malformed model output')
        result=b.compare(self.base,self.root,'fake-movie',[2],size=4,call=fail)
        self.assertEqual(len(result['windows']),1)
        self.assertIn('Malformed model output',result['windows'][0]['error'])
        self.assertTrue(all(r['candidate_japanese'] is None for r in result['entries']))


if __name__=='__main__':
    unittest.main()
