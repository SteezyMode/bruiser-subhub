"""UI terminology regression: selected-episode counts are not whole-library facts."""
import unittest
from pathlib import Path

PAGE = Path(__file__).parent / "tools" / "subhub_dashboard.html"


class CoverageReportingLabels(unittest.TestCase):
    def test_selected_season_denominators_and_translation_eligibility_are_distinct(self):
        html = PAGE.read_text(encoding="utf-8")
        self.assertIn("Selected seasons only", html)
        self.assertIn("not entire-series total", html)
        self.assertIn("eligible for PLaMo", html)
        self.assertIn("Translate checked with PLaMo (", html)
        self.assertIn("selected / ", html)
        self.assertNotIn("Last resort: checked PLaMo (", html)

    def test_review_button_is_not_reported_as_rescan(self):
        html = PAGE.read_text(encoding="utf-8")
        self.assertIn("Recheck selected episode coverage", html)
        self.assertIn("This is not a Jellyfin library rescan", html)
        self.assertIn('expanded=!expanded',html)
        self.assertIn('No episodes checked. Reviewing the list never starts translation',html)


if __name__=="__main__":
    unittest.main()
