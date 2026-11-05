"""Low-threshold source QA regression: catch trash, never punish natural Japanese."""
import unittest
from tools import ja_first_obvious_quality as qa


def sample(cues=365, damaged=None):
    items=[]
    for i in range(cues):
        message=(f"続きの台詞です{i}" if i<283
                 else f"♪ {i}" if i<363
                 else f"OK{i}")
        if damaged is not None:
            replacement=damaged(i)
            if replacement is not None:
                message=replacement
        st=103000+i*12000
        def stamp(ms):
            sec,milli=divmod(ms,1000)
            hrs,sec=divmod(sec,3600)
            minute,sec=divmod(sec,60)
            return f"{hrs:02}:{minute:02}:{sec:02},{milli:03}"
        items.append(f"{i+1}\n{stamp(st)} --> {stamp(st+1800)}\n{message}")
    return ("\n\n".join(items)+"\n").encode("utf8")


class ObviousQualityTests(unittest.TestCase):
    def test_real_film_shape_passes_without_unfair_symbol_penalty(self):
        result=qa.assess(sample())
        self.assertEqual(result["verdict"],"pass")
        self.assertEqual(result["cues"],365)
        self.assertEqual(result["signals"]["symbol_or_number_cues"],80)
        self.assertGreater(result["japanese_fraction_of_letter_cues"],.99)

    def test_normal_japanese_paraphrases_and_loanwords_do_not_block(self):
        x=sample(damaged=lambda i:
            f"すごく自然な言い方{i}" if i<250 else
            (f"カタカナと ジョン・スミス OK {i}" if i<340 else None))
        self.assertEqual(qa.assess(x)["verdict"],"pass")

    def test_bizarre_but_rare_english_or_names_do_not_block(self):
        x=sample(damaged=lambda i: f"I can't believe this {i}" if i<25 else None)
        r=qa.assess(x)
        self.assertEqual(r["verdict"],"pass")
        self.assertGreater(r["signals"]["english_sentence_cues"],20)

    def test_extensive_english_only_cues_hold(self):
        x=sample(damaged=lambda i: f"I cannot understand anything {i}" if i<115 else None)
        r=qa.assess(x)
        self.assertIn("substantial_untranslated_english",r["holds"])
        with self.assertRaisesRegex(RuntimeError,"obvious_source_quality_hold"):
            qa.require_not_garbage(x)

    def test_extreme_repeated_sentence_holds(self):
        x=sample(damaged=lambda i: "同じ文章が何度も繰り返される" if i<110 else None)
        self.assertIn("extreme_repeated_japanese_text",qa.assess(x)["holds"])

    def test_mojibake_and_placeholders_are_detected(self):
        x=sample(damaged=lambda i: "ãƒ«ãƒ‡ã‚¹" if i<60 else None)
        self.assertIn("extensive_encoding_garbage",qa.assess(x)["holds"])
        y=sample(damaged=lambda i: "TODO translate me" if i<60 else None)
        self.assertIn("placeholder_instead_of_dialogue",qa.assess(y)["holds"])

    def test_small_isolated_encoding_warning_not_fail(self):
        x=sample(damaged=lambda i: "\ufffdこれは読める台詞" if i==100 else None)
        r=qa.assess(x)
        self.assertEqual(r["verdict"],"pass")
        self.assertIn("isolated_replacement_characters",r["warnings"])

    def test_no_dialogue_leaks_into_results(self):
        x=sample()
        self.assertNotIn("続きの台詞",str(qa.assess(x)))
        self.assertNotIn("続きの台詞",str(qa.require_not_garbage(x)))

    def test_malformed_input_refused(self):
        with self.assertRaises(RuntimeError):
            qa.assess(b"THIS IS NOT AN SRT")
        with self.assertRaises(RuntimeError):
            qa.assess(b"\xff\xfe")


if __name__=="__main__":
    unittest.main()
