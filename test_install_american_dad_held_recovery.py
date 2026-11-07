"""Offline guard: one file list drives the complete recovery installer.

The previous installer validated plamo3_real_film_ab.py in its temporary
directory but downloaded/installed only two other scripts. That failed before
installation. Avoid three independently-maintained file lists.
"""
from pathlib import Path
import re
import unittest


INSTALLER = Path(__file__).parent / "tools" / "install_american_dad_held_recovery.sh"


class RecoveryInstallerFilesTests(unittest.TestCase):
    def test_download_install_and_preflight_use_one_file_list(self):
        text = INSTALLER.read_text("utf-8")
        declaration = re.search(r"^FILES=\\(([^\\n)]*)\\)$", text, re.M)
        self.assertIsNotNone(declaration)
        names = declaration.group(1).split()
        self.assertEqual(names, [
            "plamo3_real_film_ab.py",
            "plamo3_watch_american_dad.py",
            "plamo8b_american_dad_existing_en_batch.py",
        ])
        self.assertEqual(text.count('for name in "${FILES[@]}"; do'), 3)
        for name in names:
            self.assertIn('root/"' + name + '"', text)
        self.assertIn('ast.parse(a); ast.parse(b); ast.parse(c)', text)


if __name__ == "__main__":
    unittest.main()
