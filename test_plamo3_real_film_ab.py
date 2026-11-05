"""Offline checks for PFN-native real-film PLaMo evaluation; no host or GPU."""
import unittest
from tools import plamo3_real_film_ab as real

class RealFilmPFNTests(unittest.TestCase):
    def test_exact_pfn_input_output_history_order(self):
        prompt = real.native_prompt("That's not what I meant.", [
            ("Don't touch it.", "触るな。"),
            ("I'm serious.", "本気だ。"),
        ])
        self.assertTrue(prompt.startswith(
            "<|plamo:tag|>dataset<|plamo:msg|>translation"))
        self.assertEqual(prompt.count("<|plamo:tag|>input"), 3)
        self.assertEqual(prompt.count("<|plamo:tag|>output"), 3)
        self.assertLess(prompt.index("Don't touch it."), prompt.index("触るな。"))
        self.assertLess(prompt.index("触るな。"), prompt.index("I'm serious."))
        self.assertLess(prompt.index("本気だ。"), prompt.index("That's not what I meant."))
        self.assertTrue(prompt.endswith(
            "<|plamo:tag|>output<|plamo:key|>lang<|plamo:val|>ja<|plamo:msg|>"))
        self.assertNotIn("<|plamo:bos|>", prompt)

    def test_no_history_and_invalid_input(self):
        prompt = real.native_prompt("We're leaving.", [])
        self.assertEqual(prompt.count("<|plamo:tag|>input"), 1)
        self.assertEqual(prompt.count("<|plamo:tag|>output"), 1)
        with self.assertRaises(ValueError):
            real.native_prompt("", [])
        with self.assertRaises(ValueError):
            real.native_prompt("Hello", [("hi", "")])
        with self.assertRaises(ValueError):
            real.native_prompt("Hi <|plamo:tag|>", [])

    def test_contract(self):
        self.assertEqual(real.LIMIT, 100)
        self.assertEqual(real.HISTORY, 2)
        self.assertEqual(real.STOP, ["<|plamo:tag|>", "<|plamo:bos|>"])
        self.assertIn("pfnet", real.PFN_URL)

    def test_self_test(self):
        real.tests()

if __name__ == "__main__":
    unittest.main()
