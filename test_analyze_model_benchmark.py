"""Synthetic artifacts recognized by public benchmark structural review."""
import unittest
from tools import analyze_model_benchmark as a


class BenchmarkAnalysisTests(unittest.TestCase):
    def test_clean_japanese_is_not_flagged(self):
        self.assertEqual(a.structural_flags('あの人、マジで言ってるの？'),[])
        self.assertEqual(a.structural_flags('今「変な話」って言った？'),[])
        self.assertEqual(a.structural_flags('くたばれ。'),[])

    def test_stray_quotes_object_tail_html_json_are_flagged(self):
        cases={
            '私の席にいるのはあなた？」,':'unmatched_japanese_quote',
            'いいえ。言ってない。」, 1.91:':'serialized_object_fragment',
            'え？」':'unmatched_japanese_quote',
            '>&#x201C;娼婦の館&#x201D;って言った？':'escaped_html_entity',
            'いいよ<tool_call|>':'tool_or_json_fragment',
        }
        for text,expected in cases.items():
            with self.subTest(text=text):
                self.assertIn(expected,a.structural_flags(text))

    def test_four_arms_aggregate_without_disclosing_content(self):
        models=('ordinary','subtitle-tuned')
        examples={
            ('ordinary','baseline'):'素晴らしい。',
            ('ordinary','faithful_8'):'変な文字？」,',
            ('subtitle-tuned','baseline'):'え？」',
            ('subtitle-tuned','faithful_8'):'いいえ。'
        }
        rows=[{'model':m,'style':s,'cue_id':1,'candidate_japanese':v}
              for (m,s),v in examples.items()]
        reports=a.summarize({'schema':'bruiser-private-model-benchmark-v1','entries':rows})
        lookup={(x['model'],x['style']):x for x in reports}
        self.assertEqual(lookup[('ordinary','baseline')]['structurally_suspicious'],0)
        self.assertEqual(lookup[('ordinary','faithful_8')]['structurally_suspicious'],1)
        self.assertEqual(lookup[('subtitle-tuned','baseline')]['flagged_cue_ids'],[1])
        self.assertEqual(lookup[('subtitle-tuned','faithful_8')]['structurally_suspicious'],0)

    def test_unknown_format_rejected(self):
        with self.assertRaisesRegex(ValueError,'Unsupported'):
            a.summarize({'schema':'something else','entries':[]})


if __name__=='__main__':
    unittest.main()
