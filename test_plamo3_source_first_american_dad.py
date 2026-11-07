"""Real-use American Dad source-first decision tree; synthetic, offline.

Tests do not call providers, download media or change existing subtitles.
"""
import argparse
from pathlib import Path
import tempfile
import json
import sqlite3
from types import SimpleNamespace
from unittest import TestCase, main, mock

from tools import plamo3_source_first_american_dad as source
from tools import plamo3_watch_american_dad as episode
from tools import plamo3_small_ab as small


def args(requested=None):
    return argparse.Namespace(episode=requested, port=18884)


class SourceFirstEpisodeTests(TestCase):
    def test_safest_rule_existing_japanese_ends_without_model(self):
        with tempfile.TemporaryDirectory() as d:
            with mock.patch.object(episode, "MANIFEST", Path(d)/"episode.json"), \
                 mock.patch.object(source, "candidate_order",
                     return_value=([], ["S08E01"])), \
                 mock.patch.object(source,"cached_or_search_ja") as ja, \
                 mock.patch.object(source,"english_source") as en, \
                 mock.patch.object(episode,"run") as model:
                source.process_one(args("S08E01"), None,None,None,None,None,None)
            ja.assert_not_called()
            en.assert_not_called()
            model.assert_not_called()

    def test_downloadable_japanese_wins_even_when_embedded_english_exists(self):
        video=Path("/media/American.Dad.S08E01.mkv")
        choices=[((0,0,"S08E01",str(video)),"S08E01",video,True)]
        daily=SimpleNamespace(probe=lambda _:{"ja":False},
                              already_ja=lambda _:False)
        with tempfile.TemporaryDirectory() as d, \
             mock.patch.object(episode,"MANIFEST",Path(d)/"episode.json"), \
             mock.patch.object(source,"candidate_order",return_value=(choices,[])), \
             mock.patch.object(source,"latest_row",return_value={"jellyfin_id":"x"}) as manifest, \
             mock.patch.object(source,"cached_or_search_ja",return_value=[{"grade":"plausible"}]) as ja, \
             mock.patch.object(source,"acquire_ja",return_value=True) as acquired, \
             mock.patch.object(source,"english_source") as en, \
             mock.patch.object(episode,"run") as translate:
            source.process_one(args(),daily,None,None,None,None,None)
        manifest.assert_called_once_with(video)
        ja.assert_called_once()
        acquired.assert_called_once()
        en.assert_not_called()
        translate.assert_not_called()

    def test_missing_ja_uses_verified_english_then_selected_8b(self):
        video=Path("/media/American.Dad.S19E10.mkv")
        choices=[((0,1,"S19E10",str(video)),"S19E10",video,True)]
        rows=small.samples()[:2]
        daily=SimpleNamespace(probe=lambda _:{"ja":False},
                              already_ja=lambda _:False)
        with tempfile.TemporaryDirectory() as d, \
             mock.patch.object(episode,"MANIFEST",Path(d)/"episode.json"), \
             mock.patch.object(source,"candidate_order",return_value=(choices,[])), \
             mock.patch.object(source,"latest_row",return_value={"jellyfin_id":"x"}), \
             mock.patch.object(source,"cached_or_search_ja",return_value=[]), \
             mock.patch.object(source,"acquire_ja",return_value=False), \
             mock.patch.object(source,"english_source",return_value=(
                 rows,"embedded_english_from_same_file","a"*64,{"mode":"embedded"})) as en, \
             mock.patch.object(episode,"seed_verified_source") as seed, \
             mock.patch.object(episode,"run") as translate:
            source.process_one(args(),daily,None,None,None,None,None)
        en.assert_called_once()
        seed.assert_called_once()
        self.assertEqual(seed.call_args.args[1],"S19E10")
        translate.assert_called_once()
        self.assertEqual(translate.call_args.args[0].episode,"S19E10")
        self.assertTrue(translate.call_args.args[0].install)

    def test_only_american_dad_missing_series_id_is_searchable(self):
        video = Path("/media/TV/American.Dad.S19E13.mkv")
        row = {
            "status": "review_missing_series_identity",
            "kind": "Episode", "host_path": str(video),
            "jellyfin_id": "a"*32, "series_title": "American Dad!",
            "season": 19, "episode": 13,
            "series_imdb_id": "", "series_tmdb_id": "",
            "series_tvdb_id": "",
        }
        ready = source.query_eligible_episode(video, row)
        self.assertEqual(ready["status"], "ready_ja_search")
        self.assertEqual(ready["series_title"], "American Dad!")
        self.assertEqual(row["status"], "review_missing_series_identity")
        self.assertNotIn("source_first_verified", row)
        changed = dict(row, episode=14)
        with self.assertRaisesRegex(RuntimeError, "episode_number_conflicts"):
            source.query_eligible_episode(video, changed)
        changed = dict(row, series_title="The Simpsons")
        with self.assertRaisesRegex(RuntimeError, "not_american_dad"):
            source.query_eligible_episode(video, changed)
        changed = dict(row, jellyfin_id="")
        with self.assertRaisesRegex(RuntimeError, "invalid_jellyfin_item"):
            source.query_eligible_episode(video, changed)
        changed = dict(row, status="review_missing_media_streams")
        with self.assertRaisesRegex(RuntimeError, "unverified_japanese_catalog"):
            source.query_eligible_episode(video, changed)

    def test_real_sublarr_japanese_search_accepts_verified_episode_without_provider_id(self):
        from tools import ja_first_search_pilot as ja_search
        with tempfile.TemporaryDirectory() as td:
            video=Path(td)/"American.Dad.S19E13.mkv"
            video.write_bytes(b"synthetic harmless fixture")
            row={"status":"review_missing_series_identity","kind":"Episode",
                 "host_path":str(video),"jellyfin_id":"a"*32,
                 "series_title":"American Dad!","season":19,"episode":13,
                  "audio_language":"eng",
                 "series_imdb_id":"","series_tmdb_id":"","series_tvdb_id":""}
            eligible=source.query_eligible_episode(video,row)
            query=ja_search.query_for(eligible)
            self.assertEqual(query["series_title"],"American Dad!")
            self.assertEqual(query["season"],19)
            self.assertEqual(query["episode"],13)
            self.assertEqual(query["language"],"ja")
            self.assertNotIn("imdb_id",query)
            # A provider title lookup must not bypass verified primary audio.
            self.assertIsNone(ja_search.query_for(dict(eligible,audio_language="")))
            self.assertIsNone(ja_search.query_for(dict(eligible,audio_language="jpn")))
            self.assertEqual(row["status"],"review_missing_series_identity")

    def test_missing_series_id_generates_real_japanese_provider_query(self):
        video = Path("/media/TV/American.Dad.S19E13.mkv")
        row = {"status": "review_missing_series_identity", "kind": "Episode",
               "host_path": str(video), "jellyfin_id": "c"*32,
               "series_title": "American Dad!", "season": 19, "episode": 13}
        query = {"file_path": "", "language": "ja",
                 "series_title": "American Dad!", "season": 19, "episode": 13}
        fake = SimpleNamespace(
            query_for=mock.Mock(return_value=query),
            open_db=mock.Mock(side_effect=RuntimeError("STOP_BEFORE_PROVIDER"))
        )
        with self.assertRaisesRegex(RuntimeError, "STOP_BEFORE_PROVIDER"):
            source.cached_or_search_ja(video,row,fake)
        sent = fake.query_for.call_args.args[0]
        self.assertEqual(sent["status"],"ready_ja_search")
        self.assertEqual(sent["season"],19)
        self.assertEqual(sent["episode"],13)

    def test_japanese_provider_error_allows_verified_english_fallback(self):
        video=Path("/media/American.Dad.S19E13.mkv")
        choices=[((0,0,"S19E13",str(video)),"S19E13",video,True)]
        daily=SimpleNamespace(probe=lambda _:{"ja":False},
                              already_ja=lambda _:False)
        sample=small.samples()[:2]
        with tempfile.TemporaryDirectory() as d, \
             mock.patch.object(episode,"MANIFEST",Path(d)/"episode.json"), \
             mock.patch.object(source,"candidate_order",return_value=(choices,[])), \
             mock.patch.object(source,"latest_row",return_value={"jellyfin_id":"x"}), \
             mock.patch.object(source,"cached_or_search_ja",
                               side_effect=RuntimeError("ja_search_unavailable")), \
             mock.patch.object(source,"english_source",
                               return_value=(sample,"embedded", "f"*64, {"mode":"embedded"})) as english, \
             mock.patch.object(episode,"seed_verified_source") as seed, \
             mock.patch.object(episode,"run") as model:
            source.process_one(args(), daily,None,None,None,None,None)
        english.assert_called_once()
        seed.assert_called_once()
        model.assert_called_once()

    def test_no_english_subtitles_does_not_fabricate_from_audio(self):
        video=Path("/media/American.Dad.S08E02.mkv")
        choices=[((1,0,"S08E02",str(video)),"S08E02",video,False)]
        daily=SimpleNamespace(probe=lambda _:{"ja":False},
                              already_ja=lambda _:False)
        with tempfile.TemporaryDirectory() as d, \
             mock.patch.object(episode,"MANIFEST",Path(d)/"episode.json"), \
             mock.patch.object(source,"candidate_order",return_value=(choices,[])), \
             mock.patch.object(source,"latest_row",return_value={"jellyfin_id":"x"}), \
             mock.patch.object(source,"cached_or_search_ja",return_value=[]), \
             mock.patch.object(source,"acquire_ja",return_value=False), \
             mock.patch.object(source,"english_source",return_value=None), \
             mock.patch.object(episode,"run") as model:
            source.process_one(args(),daily,None,None,None,None,None)
        model.assert_not_called()

    def test_audio_sync_external_english_preserves_dialogue_and_corrects_time(self):
        before=[{"start":5000,"end":6000,"text":"Hello."},
                {"start":8000,"end":9000,"text":"I know."}]*80
        after=[dict(c,start=c["start"]+1800,end=c["end"]+1800)
               for c in before]
        ffsync=SimpleNamespace(
            parse_cues=mock.Mock(side_effect=[before,after]),
            align_in_container=mock.Mock(return_value=b"aligned"),
        )
        result,meta=source.validate_timing_source(
            Path("/media/episode.mkv"),b"original","external",ffsync)
        self.assertEqual(result,b"aligned")
        self.assertEqual(meta["mode"],"audio_verified_ffsubsync")
        self.assertEqual(meta["shift_range_seconds"],[1.8,1.8])

    def test_audio_sync_rejects_dialogue_mutation(self):
        before=[{"start":i*2000,"end":i*2000+1000,"text":"Original"}
                for i in range(180)]
        after=[dict(x) for x in before]
        after[9]["text"]="Changed"
        ff=SimpleNamespace(parse_cues=mock.Mock(side_effect=[before,after]),
                           align_in_container=lambda *_:b"aligned")
        with self.assertRaisesRegex(RuntimeError,"changed_dialogue"):
            source.validate_timing_source(Path("/ep.mkv"),b"raw","external",ff)

    def test_exact_hash_english_only_and_numbering_protection(self):
        row={"jellyfin_id":"a"*32,"season":8,"episode":1}
        candidates=[
            {"Id":"wrong","Format":"srt","ThreeLetterISOLanguageName":"eng",
             "IsHashMatch":False},
            {"Id":"wrong_number","Format":"srt","ThreeLetterISOLanguageName":"eng",
             "IsHashMatch":True,"Name":"American.Dad.S08E02"},
            {"Id":"correct","Format":"srt","ThreeLetterISOLanguageName":"eng",
             "IsHashMatch":True,"Name":"American.Dad.S08E01",
             "DownloadCount":15},
        ]
        client=SimpleNamespace(get=mock.Mock(return_value=candidates),
                               post=mock.Mock(return_value=None))
        self.assertTrue(source.jellyfin_english_download(row,client))
        self.assertEqual(client.post.call_count,1)
        self.assertIn("correct",client.post.call_args.args[0])
        self.assertNotIn("wrong",client.post.call_args.args[0])

    def test_cached_ja_miss_does_not_make_repeated_provider_request(self):
        with tempfile.TemporaryDirectory() as td:
            dbpath=Path(td)/"search.sqlite3"
            with sqlite3.connect(dbpath) as db:
                db.execute("CREATE TABLE searches (jellyfin_id TEXT, searched_at INT,"
                           "outcome TEXT,results_json TEXT)")
                import time
                db.execute("INSERT INTO searches VALUES (?,?,?,?)",
                           ("x",int(time.time()),"none",
                            json.dumps({"candidates":[] })))
            fake=SimpleNamespace(
                open_db=lambda: sqlite3.connect(dbpath),
                query_for=lambda row:{"language":"ja"},
            )
            with mock.patch.object(source.subprocess,"run") as network:
                got=source.cached_or_search_ja(
                    Path("/media/AD.S08E01.mkv"),
                    {"status":"ready_ja_search","jellyfin_id":"x"},fake)
            self.assertEqual(got,[])
            network.assert_not_called()


if __name__ == "__main__":
    main()
