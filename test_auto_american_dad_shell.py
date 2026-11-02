"""Shell launcher syntax and dangerous-command regression checks."""
from pathlib import Path
import subprocess
import unittest


class AutoShellTests(unittest.TestCase):
    def test_syntax_and_host_safety(self):
        root=Path(__file__).resolve().parent
        script=root/'tools/auto_american_dad.sh'
        p=subprocess.run(['bash','-n',str(script)],
                         capture_output=True,text=True,timeout=10)
        self.assertEqual(p.returncode,0,p.stderr)
        content=script.read_text(encoding='utf8')
        self.assertIn('python3 -m venv',content)
        self.assertIn('faster-whisper==1.2.1',content)
        self.assertIn('enable_american_dad_timer.py',content)
        self.assertIn('american_dad_maintenance.py',content)
        self.assertIn('american_dad_autopilot.py',content)
        self.assertNotIn('sudo ',content)
        self.assertNotIn('systemctl restart jellyfin',content)
        self.assertNotIn('docker restart',content)
        self.assertNotIn('ollama pull',content)
        self.assertNotIn('rm -rf',content)


    def test_supervised_worker_repair_launcher_syntax_and_safety(self):
        root=Path(__file__).resolve().parent
        script=root/'tools/repair_american_dad_worker.sh'
        p=subprocess.run(['bash','-n',str(script)],
                         capture_output=True,text=True,timeout=10)
        self.assertEqual(p.returncode,0,p.stderr)
        body=script.read_text(encoding='utf8')
        self.assertIn('american_dad_maintenance.py',body)
        self.assertIn('enable_american_dad_timer.py',body)
        self.assertIn('Type=exec',body)
        self.assertIn('RuntimeMaxSec=11h',body)
        self.assertIn('start --no-block',body)
        self.assertNotIn('sudo ',body)
        self.assertNotIn('systemctl restart',body)
        self.assertNotIn('docker restart',body)
        self.assertNotIn('rm -rf',body)
        self.assertNotIn('pip install',body)

if __name__=='__main__':
    unittest.main()
