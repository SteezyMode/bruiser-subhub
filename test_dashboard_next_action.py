"""Offline regression for the operator-first SubHub dashboard layout."""
import unittest
from pathlib import Path

PAGE = Path(__file__).parent / "tools" / "subhub_dashboard.html"


class DashboardNextActionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = PAGE.read_text("utf-8")

    def test_summary_precedes_technical_details_and_title_search(self):
        html = self.html
        self.assertLess(html.index('id="next-step"'), html.index('id="active-work"'))
        self.assertLess(html.index('id="active-work"'), html.index('id="library-details"'))
        self.assertLess(html.index('id="library-details"'), html.index('id="lookup"'))
        self.assertIn('<details class="panel" id="library-details">', html)
        self.assertIn('<details id="daily-downloads"', html)

    def test_no_work_is_started_on_page_load(self):
        html = self.html
        self.assertIn('function renderNextStep(d)', html)
        self.assertIn('button.dataset.target=target', html)
        self.assertIn('if(target==="library-details")$("library-details").open=true', html)
        self.assertIn('if(target==="lookup")$("title-search").focus()', html)
        # The summary button only navigates. Existing explicit owner handlers own work.
        segment = html.split('$("next-action").addEventListener("click"', 1)[1]
        segment = segment.split('async function refreshStatus(){', 1)[0]
        self.assertNotIn("ownerPost(", segment)
        self.assertNotIn("systemctl", segment)

    def test_selected_series_displays_missing_episodes_by_default(self):
        html = self.html
        self.assertIn('selectedSeasons.add(n)', html)
        self.assertIn('expanded=true;', html)
        self.assertIn('entry.seasons.slice(i,i+4).map(loadSeason)', html)
        self.assertIn('showCovered||it.status!=="covered"', html)
        self.assertIn('Saved queue and sidecars; may lag Jellyfin.', html)

    def test_searched_is_not_labeled_as_published(self):
        html = self.html
        self.assertIn('Search attempts and downloaded candidates are not completed results.', html)
        self.assertIn('Only published Japanese sidecars count as complete.', html)


if __name__ == "__main__":
    unittest.main()
