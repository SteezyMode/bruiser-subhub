"""Offline guard: one file list drives the complete recovery installer.

The previous installer validated plamo3_real_film_ab.py in its temporary
directory but downloaded/installed only two other scripts. That failed before
installation. Avoid three independently-maintained file lists.
"""
from pathlib import Path
import unittest


INSTALLER = Path(__file__).parent / "tools" / "install_american_dad_held_recovery.sh"


class RecoveryInstallerFilesTests(unittest.TestCase):
    def test_download_install_and_preflight_use_one_file_list(self):
        text = INSTALLER.read_text("utf-8")
        declaration = next((line for line in text.splitlines()
                            if line.startswith("FILES=(")), None)
        self.assertIsNotNone(declaration)
        names = declaration.removeprefix("FILES=(").removesuffix(")").split()
        self.assertEqual(names, [
            "plamo3_real_film_ab.py",
            "plamo3_watch_american_dad.py",
            "plamo8b_american_dad_existing_en_batch.py",
        ])
        self.assertEqual(text.count('for name in "${FILES[@]}"; do'), 3)
        self.assertIn('FILES+=(subhub_plamo_handoff.py)', text)
        self.assertIn('MODE="${2:-restart}"', text)
        self.assertIn('if [[ "$MODE" == "--install-only" ]]; then', text)
        self.assertLess(text.index('if [[ "$MODE" == "--install-only" ]]; then'),
                        text.index('nohup python3'))
        self.assertIn('assert "batch.thermal_gate()" in g',text)
        for name in names:
            self.assertIn('root/"' + name + '"', text)
        self.assertIn('ast.parse(a); ast.parse(b); ast.parse(c)', text)


if __name__ == "__main__":
    unittest.main()
