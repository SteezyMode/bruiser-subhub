"""Coverage queue: offline source-first policy, timing priority, persistence."""
from pathlib import Path
import tempfile
import unittest

from tools import bruiser_coverage_queue as queue


def media(**kwargs):
    base = dict(
        video_path="/media/Example.Show.S01E01.mkv",
        jellyfin_id="jid-one",kind="Episode",series="Example Show",
        title="Episode 1",season=1,episode=1,category="english_only",
        audio_language="en",english_subtitles=True,
        japanese_subtitles=False,english_text=True,
        english_verification="actual_embedded_english_confirmed"
    )
    base.update(kwargs)
    return base


class CoverageQueueTests(unittest.TestCase):
    def test_english_audio_search_japanese_first(self):
        items=queue.tasks_for(media())
        self.assertEqual([(t[0],t[1]) for t in items],[("ja","search_ja")])

    def test_cached_japanese_downloads_before_new_search(self):
        row=media()
        self.assertEqual(queue.tasks_for(row,staged={"jid-one"})[0][1],
                         "align_existing_staged_ja")
        self.assertEqual(queue.tasks_for(row,searches={
            "jid-one":("plausible",2,2000000000)},now=2000000020)[0][1],
                         "download_saved_ja")
        self.assertEqual(queue.tasks_for(row,searches={
            "jid-one":("review",0,2000000000)},now=2000000020)[0][1],
                         "review_saved_ja")

    def test_one_provider_miss_is_not_translation_authorization(self):
        plan=queue.tasks_for(media(),searches={
            "jid-one":("none",0,2000000000)},now=2000000100)
        self.assertEqual(plan[0][1],"search_ja")
        self.assertIn("expand_providers",plan[0][2])
        self.assertEqual(queue.tasks_for(media(english_text=False),searches={
            "jid-one":("none",0,2000000000)},now=2000000100)[0][1],
                         "search_ja")
        # A stale miss remains eligible for a fresh provider search, not AI.
        self.assertEqual(queue.tasks_for(media(),searches={
            "jid-one":("none",0,2000000000)},now=2000000000+40*86400)[0][1],
                         "search_ja")

    def test_japanese_audio_requires_english_not_japanese(self):
        items=queue.tasks_for(media(audio_language="jpn",
            japanese_subtitles=True,english_subtitles=False,category="japanese_only"))
        self.assertEqual([(x[0],x[1]) for x in items],[("en","search_en")])

    def test_third_language_requires_both(self):
        items=queue.tasks_for(media(audio_language="es",
            english_subtitles=False,english_text=False,
            japanese_subtitles=False,category="neither"))
        self.assertEqual({x[0] for x in items},{"en","ja"})

    def test_ambiguous_never_causes_automatic_provider_work(self):
        items=queue.tasks_for(media(category="unknown"))
        self.assertEqual(items[0][1],"review_uncertain")

    def test_unknown_audio_can_discover_japanese_without_assuming_english(self):
        for audio in ("unknown", "und", "", "mul", "zxx", "none"):
            row=media(audio_language=audio,category="neither",
                      english_subtitles=False,japanese_subtitles=False)
            planned=queue.tasks_for(row)
            self.assertEqual([(r[0],r[1]) for r in planned],
                             [("ja","search_ja"),("review","review_uncertain")])
            self.assertIn("audio_unverified",planned[0][2])
            self.assertIn("primary_audio_language_unverified",planned[1][2])

    def test_unknown_audio_never_translates_even_with_english_available(self):
        row=media(audio_language="unknown",category="english_only",
                  english_subtitles=True,japanese_subtitles=False)
        planned=queue.tasks_for(row,searches={
            "jid-one":("none",0,2000000000)},now=2000000100)
        self.assertEqual([(r[0],r[1]) for r in planned],
                         [("ja","search_ja"),("review","review_uncertain")])

    def test_unknown_audio_with_both_subtitles_needs_no_work(self):
        self.assertEqual(queue.tasks_for(media(audio_language="unknown",
            category="both",english_subtitles=True,japanese_subtitles=True)),[])

    def test_already_subtitled_is_skipped(self):
        self.assertEqual(queue.tasks_for(media(category="both",
            japanese_subtitles=True)),[])

    def test_repair_outprioritizes_download_and_persists(self):
        with tempfile.TemporaryDirectory() as temp:
            with queue.queue_db(Path(temp)/"state") as db:
                row=media(japanese_subtitles=True,category="both")
                result=queue.import_snapshot(db,[row],"a"*64,"test.json")
                self.assertEqual(result["active_tasks"],0)
                raised=queue.flag_timing(db,"jid-one","en","uniform offset 2s")
                self.assertEqual(raised["language"],"en")
                task=queue.next_tasks(db)[0]
                self.assertEqual(task["action"],"repair_existing_timing")
                self.assertEqual(task["priority"],0)
                self.assertEqual(queue.report(db)["timing_repairs_flagged"],1)
            with queue.queue_db(Path(temp)/"state") as db:
                self.assertEqual(queue.next_tasks(db)[0]["action"],
                                 "repair_existing_timing")
                self.assertEqual(queue.import_snapshot(
                    db,[row],"a"*64,"test.json")["result"],
                    "reconciled_existing_snapshot")

    def test_task_state_survives_new_snapshot(self):
        with tempfile.TemporaryDirectory() as temp:
            with queue.queue_db(Path(temp)/"state") as db:
                row=media()
                queue.import_snapshot(db,[row],"a"*64,"old")
                queue.update_task_state(db,"jid-one","ja","held","needs QA")
                queue.import_snapshot(db,[row],"b"*64,"new")
                state=db.execute("SELECT state,note,attempts FROM tasks").fetchone()
                self.assertEqual(tuple(state),("held","needs QA",1))
                repaired=media(japanese_subtitles=True,category="both")
                queue.import_snapshot(db,[repaired],"c"*64,"newer")
                self.assertEqual(queue.report(db)["active_tasks"],0)

    def test_same_matrix_new_saved_provider_candidate_reactivates_hold(self):
        with tempfile.TemporaryDirectory() as temp:
            with queue.queue_db(Path(temp)/"state") as db:
                row=media()
                queue.import_snapshot(db,[row],"a"*64,"test")
                queue.update_task_state(db,"jid-one","ja","held","prior lack of match")
                refreshed=queue.import_snapshot(
                    db,[row],"a"*64,"test",
                    searches={"jid-one":("plausible",1,2000000000)})
                self.assertEqual(refreshed["result"],
                                 "reconciled_existing_snapshot")
                task=db.execute("SELECT action,state FROM tasks").fetchone()
                self.assertEqual(tuple(task),("download_saved_ja","pending"))
                self.assertEqual(queue.report(db)["snapshots"],1)

    def test_refuse_timing_repair_without_existing_track(self):
        with tempfile.TemporaryDirectory() as temp:
            with queue.queue_db(Path(temp)/"state") as db:
                queue.import_snapshot(db,[media()],"a"*64,"test")
                with self.assertRaisesRegex(RuntimeError,"No existing subtitle"):
                    queue.flag_timing(db,"jid-one","ja","delay")

    def test_soft_preference_no_type_quota(self):
        self.assertEqual(queue.preference(media(series="The X-Files")),
                         queue.preference(media(series="Another Show")))
        self.assertLess(queue.preference(media(kind="Movie",
            video_path="/media/Movies/Horror/Example.mkv")),
            queue.preference(media(kind="Movie",
            video_path="/media/Movies/Comedy/Example.mkv")))


if __name__=="__main__":
    unittest.main()
