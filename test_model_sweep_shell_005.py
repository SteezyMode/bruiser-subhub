"""Lint model-sweep entrypoint shell syntax in CI; no SSH/GPU calls."""
from pathlib import Path
import shutil
import subprocess
import unittest


class SweepBashSyntaxTests(unittest.TestCase):
    def test_shell_runner_syntax(self):
        if not shutil.which('bash'):
            self.skipTest('Bash unavailable')
        root=Path(__file__).resolve().parent
        for path in ('tools/run_model_sweep_005.sh','tools/run_cat33_005.sh',
                     'tools/diagnose_model_sweep_005.sh'):
            with self.subTest(path=path):
                result=subprocess.run(['bash','-n',str(root/path)],
                                      capture_output=True,text=True)
                self.assertEqual(result.returncode,0,result.stderr)

if __name__=='__main__':
    unittest.main()
