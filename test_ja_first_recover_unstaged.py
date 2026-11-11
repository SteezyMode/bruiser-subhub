"""Offline source-first recovery selection: avoid re-downloading held JA stages."""
import sys
from pathlib import Path
import unittest
from unittest.mock import Mock
sys.path.insert(0,str(Path(__file__).resolve().parent/"tools"))
try:
    import ja_first_recover_unstaged as recover
finally:
    sys.path.pop(0)

class TargetSelectionTests(unittest.TestCase):
    def test_exact_series_without_stages_only(self):
        def row(jid, season, ep, status="ready_ja_search", series="Sample Series"):
            return {"kind":"Episode","jellyfin_id":jid,
                    "series_title":series, "season":season,"episode":ep,
                    "host_path":"/media/file-"+jid+".mkv","status":status}
        records=[
            row("aa",1,2),row("bb",1,3),row("cc",1,4),
            row("dd",2,1),row("ee",1,6,"existing_japanese_subtitle"),
            row("ff",2,2,series="Other")
        ]
        from unittest.mock import patch
        with patch.object(Path,"is_file",return_value=True), patch.object(
                Path,"is_symlink",return_value=False):
            targets,staged,covered=recover.prepare(
                records,{"bb"}, "Sample Series",
                sidecar_checker=lambda video:video.name=="file-cc.mkv")
        self.assertEqual([x["jellyfin_id"] for x in targets],["aa","dd"])
        self.assertEqual([x["jellyfin_id"] for x in staged],["bb"])
        self.assertEqual([x["jellyfin_id"] for x in covered],["cc"])

if __name__=="__main__":
    unittest.main()
