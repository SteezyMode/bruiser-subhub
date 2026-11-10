"""Offline, no-network validation of the narrow live-source install patch."""
from pathlib import Path
import tempfile
import unittest
from unittest import mock
from tools import ja_first_search_pilot as source
from tools import subhub_season_sources as season

# Install script lives in tools but exposes no host actions on import.
from tools import install_manual_title_source_fallback as patch


class ManualTitleInstallTests(unittest.TestCase):
    def test_baseline_code_can_be_patched_and_reimported(self):
        for current_text,one,two,path in (
            (Path(source.__file__).read_text("utf-8"),
             (patch.SRC_OLD_ONE,patch.SRC_NEW_ONE),
             (patch.SRC_OLD_TWO,patch.SRC_NEW_TWO),
             patch.SOURCE),
            (Path(season.__file__).read_text("utf-8"),
             (patch.SEASON_OLD_ONE,patch.SEASON_NEW_ONE),
             (patch.SEASON_OLD_TWO,patch.SEASON_NEW_TWO),
             patch.SEASON),
        ):
            self.assertEqual(current_text.count(one[1]),1)
            self.assertEqual(current_text.count(two[1]),1)
            previous=current_text.replace(one[1],one[0]).replace(two[1],two[0])
            with tempfile.TemporaryDirectory() as td:
                temp=Path(td)/path.name
                temp.write_text(previous,"utf-8")
                with mock.patch.object(patch,"SOURCE",temp if path==patch.SOURCE else patch.SOURCE), \
                     mock.patch.object(patch,"SEASON",temp if path==patch.SEASON else patch.SEASON):
                    prior,result,already=patch.patch_one(
                        temp,[one,two])
                self.assertFalse(already)
                self.assertEqual(prior,previous)
                self.assertEqual(result,current_text)

    def test_unknown_source_is_not_touched(self):
        with tempfile.TemporaryDirectory() as td:
            temp=Path(td)/"unfamiliar.py"
            temp.write_text("print('local customization')\n")
            with self.assertRaises(RuntimeError):
                patch.patch_one(temp,[(patch.SRC_OLD_ONE,patch.SRC_NEW_ONE)])
            self.assertEqual(temp.read_text(),"print('local customization')\n")


if __name__=="__main__":
    unittest.main()
