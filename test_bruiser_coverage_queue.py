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

    def test_gpu_fallback_exists_after_source_failure(self):
        plan=queue.tasks_for(media(),searches={
            "jid-one":("none",0,2000000000)},now=2000000100)
        self.assertEqual(plan[0][1],"validate_english_for_ja_fallback")
        self.assertEqual(queue.tasks_for(media(english_text=False),searches={
            "jid-one":("none",0,2000000000)},now=2000000100)[0][1],
                         "recover_english_for_ja_fallback")

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
                    db,[row],"a"*64,"test.json")["result"],"already_imported")

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

    def test_refuse_timing_repair_without_existing_track(self):
        with tempfile.TemporaryDirectory() as temp:
            with queue.queue_db(Path(temp)/"state") as db:
                queue.import_snapshot(db,[media()],"a"*64,"test")
                with self.assertRaisesRegex(RuntimeError,"No existing subtitle"):
                    queue.flag_timing(db,"jid-one","ja","delay")

    def test_soft_preference_no_type_quota(self):
        self.assertLess(queue.preference(media(series="The X-Files")),
                        queue.preference(media()))
        self.assertLess(queue.preference(media(kind="Movie",
            video_path="/media/Movies/Horror/Example.mkv")),
            queue.preference(media(kind="Movie",
            video_path="/media/Movies/Comedy/Example.mkv")))


if __name__=="__main__":
    unittest.main()
