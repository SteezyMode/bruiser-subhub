"""UI terminology regression: selected-episode counts are not whole-library facts."""
import unittest
from pathlib import Path

PAGE = Path(__file__).parent / "tools" / "subhub_dashboard.html"


class CoverageReportingLabels(unittest.TestCase):
    def test_selected_season_denominators_and_translation_eligibility_are_distinct(self):
        html = PAGE.read_text(encoding="utf-8")
        self.assertIn("loaded/selected seasons", html)
        self.assertIn("Saved queue and sidecars; may lag Jellyfin.", html)
        self.assertIn("Find Japanese first; translate only when recovery is exhausted.", html)
        self.assertIn("Translate checked with PLaMo (", html)
        self.assertIn("selected / ", html)
        self.assertNotIn("Last resort: checked PLaMo (", html)

    def test_review_button_is_not_reported_as_rescan(self):
        html = PAGE.read_text(encoding="utf-8")
        self.assertIn("Recheck selected episode coverage", html)
        self.assertIn("This is not a Jellyfin library rescan", html)
        self.assertIn('expanded=!expanded',html)
        self.assertIn('Review the missing episodes below.',html)


if __name__=="__main__":
    unittest.main()
