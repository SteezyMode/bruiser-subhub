"""The one-shot search audit stays read-only and reports historical state."""
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from tools import audit_subhub_sourcing as audit


class SearchAuditTests(unittest.TestCase):
    def test_readonly_saved_history_and_version(self):
        with tempfile.TemporaryDirectory() as folder:
            db=Path(folder)/"japanese-search.sqlite3"
            source=Path(folder)/"source.py"
            source.write_text('x={"strategy_version": 4}\n')
            with sqlite3.connect(db) as con:
                con.execute("""CREATE TABLE searches (
                    kind TEXT,title TEXT,outcome TEXT,
                    results_json TEXT,searched_at INTEGER)""")
                con.execute("INSERT INTO searches VALUES(?,?,?,?,?)",(
                    "Movie","Bride of Chucky","none",
                    json.dumps({"provider_total":52,
                        "rejected_candidates":[{"provider":"opensubtitles"}],
                        "strategy_version":3,"query_variant":"title_only_fallback"}),
                    4))
            with patch.object(audit,"DB",db),patch.object(audit,"WORKER",source):
                self.assertEqual(audit.installed_version(),"4")
                report=audit.saved_report()
                self.assertEqual(report["records"],1)
                self.assertEqual(report["outcomes"],{"none":1})
                self.assertEqual(report["latest_titles"][0]["reported_hits"],52)
                with sqlite3.connect(db) as con:
                    self.assertEqual(con.execute("SELECT outcome FROM searches").fetchone()[0],
                                     "none")

    def test_partial_search_included_in_journal_audit(self):
        lines="\n".join([
            "RUNNING_SOURCES_ONLY_CYCLE search_budget=2 stage_budget=1 publish_limit=1",
            "[1/2] PARTIAL: plausible=0 review=0 provider_total=0 incomplete=subdl",
            "[2/2] NONE: plausible=0 review=0 provider_total=0",
            "AUTOFILL_CYCLE_COMPLETE"
        ])
        with patch.object(audit,"subprocess_output",return_value=lines):
            result=audit.journal_report()
        self.assertEqual(result["search_outcomes"],{"PARTIAL":1,"NONE":1})
        self.assertTrue(result["pipeline_completed"])

    def test_deferred_cycle_separate_from_pipeline_completion(self):
        logs="\n".join([
            "RUNNING_SOURCES_ONLY_CYCLE search_budget=600 stage_budget=200 publish_limit=200",
            "Search requests planned: 600 | budget: 600",
            "[44/600] NONE: plausible=0 review=0",
            "[45/600] DEFERRED: {'opensubtitles': 'budget_exhausted'}",
            "AUTOFILL_CYCLE_COMPLETE",
        ])
        with patch.object(audit,"subprocess_output",return_value=logs):
            state=audit.journal_report()
        self.assertEqual(state["search_outcomes"],{"NONE":1,"DEFERRED":1})
        self.assertEqual(state["last_search_index"],45)
        self.assertTrue(state["pipeline_completed"])
        self.assertEqual(len(state["deferred_or_limit_events"]),1)


if __name__=="__main__":
    unittest.main()
