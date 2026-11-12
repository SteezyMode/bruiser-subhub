"""Offline indexed-browser tests; no Jellyfin, providers or media writes."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from tools import subhub_library_browser as browser
from tools import subhub_finish_scope as finish
from tools import subhub_deep_source as deep


class LibraryBrowserTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name)
        action=self.base/"Movies"/"Action"
        action.mkdir(parents=True)
        self.ultron=action/"Avengers Age of Ultron (2015).mkv"
        self.crawl=action/"Crawl (2019).mkv"
        self.unknown=action/"Bad metadata.mkv"
        for path in (self.ultron,self.crawl,self.unknown):
            path.write_bytes(b"small test video file")
        self.ultron.with_name(self.ultron.stem+".ja.srt").write_text(
            "1\n00:00:01,000 --> 00:00:02,000\n字幕\n",encoding="utf-8")
        self.rows=[
            self.movie(self.ultron,"Avengers: Age of Ultron",status="ready_ja_search",
                       genres=["Action"]),
            self.movie(self.crawl,"Crawl",status="ready_ja_search",
                       genres=["Action","Horror"]),
            self.movie(self.unknown,"Bad metadata",
                       status="review_missing_path",genres=["Action"])]
        self.manifest=self.base/"ja-intake-20261112T010101Z.json"
        self.manifest.write_text(json.dumps(
            {"schema":1,"generated_utc":"2026-11-12T01:01:01Z",
             "items":self.rows}),encoding="utf-8")
        browser._CACHE.update(until=0.0,signature=None,items=None,generated="")

    def movie(self,path,title,status="ready_ja_search",genres=None):
        return {"kind":"Movie","jellyfin_id":format(
                    len(title)*101, "032x"),
                "host_path":str(path),"title":title,"year":2015,
                "status":status,"genres":genres or []}

    def test_action_genre_shows_ultron_covered_but_only_crawl_selectable(self):
        with mock.patch.object(browser.coverage,"latest_manifest",
                               return_value=self.manifest):
            data=browser.browse(kind="Movie",genre="Action")
            missing=browser.browse(kind="Movie",genre="Action",
                                   state="needs_japanese")
        states={x["title"]:x["state"] for x in data["items"]}
        self.assertEqual(states["Avengers: Age of Ultron"],"covered")
        self.assertEqual(states["Crawl"],"needs_japanese")
        self.assertEqual(states["Bad metadata"],"unverified")
        self.assertEqual([x["title"] for x in missing["items"]],["Crawl"])
        self.assertEqual(data["scope_counts"]["covered"],1)
        self.assertEqual(data["scope_counts"]["needs_japanese"],1)
        self.assertEqual(data["scope_counts"]["unverified"],1)

    def test_folder_navigation_is_real_and_boundary_aware(self):
        with mock.patch.object(browser.coverage,"latest_manifest",
                               return_value=self.manifest):
            top=browser.browse(kind="Movie")
            self.assertEqual(len(top["folders"]),1)
            self.assertEqual(top["folders"][0]["category"],"Action")
            combined=browser.browse(kind="Movie",category="Action")
            self.assertEqual(combined["matching_items"],3)
            self.assertEqual(combined["folders"],[])
            root=browser.root_for(str(self.crawl),"Movie")
            child=browser.browse(kind="Movie",folder=root)
            self.assertTrue(child["folders"])
            with self.assertRaisesRegex(ValueError,"folder_not_in"):
                browser.browse(kind="Movie",folder=root+"-wrong")

    def test_nested_movie_release_folders_display_all_selectable_missing_files(self):
        # Reported Action view: four movie release folders plus one movie
        # directly in Action. All five are real Jellyfin catalog entries.
        action=self.base/"Movies"/"Action"
        for i,title in enumerate(("Infernal Affairs", "Iron Man", "Sisu", "The Raid"),1):
            folder=action/(title+" (release)")
            folder.mkdir()
            video=folder/(title+".mkv")
            video.write_bytes(b"synthetic video")
            item=self.movie(video,title,status="ready_ja_search",genres=["Action"])
            item["jellyfin_id"]=format(1000+i,"032x")
            self.rows.append(item)
        self.manifest.write_text(json.dumps(
            {"schema":1,"generated_utc":"2026-11-12T01:01:01Z",
             "items":self.rows}),encoding="utf-8")
        browser._CACHE.update(until=0.0,signature=None,items=None,generated="")
        with mock.patch.object(browser.coverage,"latest_manifest",
                               return_value=self.manifest):
            data=browser.browse(kind="Movie",folder=str(action),
                                state="needs_japanese")
        self.assertEqual(data["scope_counts"]["needs_japanese"],5)
        self.assertEqual(len(data["items"]),5)
        self.assertEqual({x["title"] for x in data["items"]},{
            "Crawl","Infernal Affairs","Iron Man","Sisu","The Raid"})
        self.assertTrue(all(x["state"]=="needs_japanese" for x in data["items"]))
        self.assertEqual(data["matching_items"],5)
        self.assertEqual(data["folders"],[])

    def test_identical_horror_folders_across_drives_merge_without_symlinks(self):
        # Two existing Jellyfin movie roots, identical physical category name.
        a=self.base/"DriveA"/"Movies"/"Horror"
        b=self.base/"DriveB"/"Movies"/"Horror"
        a.mkdir(parents=True);b.mkdir(parents=True)
        for jid,home,title in (
            ("a"*32,a,"Film One"),("b"*32,b,"Film Two")):
            (home/title).mkdir()
            video=home/title/(title+".mkv")
            video.write_bytes(b"mock movie")
            item=self.movie(video,title,status="ready_ja_search",
                            genres=["Horror"])
            item["jellyfin_id"]=jid
            self.rows.append(item)
        self.manifest.write_text(json.dumps(
            {"schema":1,"generated_utc":"2026-11-12T01:01:01Z",
             "items":self.rows}),encoding="utf-8")
        browser._CACHE.update(until=0.0,signature=None,items=None,generated="")
        with mock.patch.object(browser.coverage,"latest_manifest",
                               return_value=self.manifest):
            home=browser.browse(kind="Movie")
            horror=[d for d in home["folders"] if d["label"]=="Horror"]
            self.assertEqual(len(horror),1)
            self.assertEqual(horror[0]["needs_japanese"],2)
            combined=browser.browse(kind="Movie",category="Horror")
            self.assertEqual(combined["matching_items"],2)
            self.assertEqual(combined["scope_counts"]["needs_japanese"],2)
            self.assertEqual(combined["folders"],[])
            self.assertEqual({r["jellyfin_id"] for r in combined["items"]},
                             {"a"*32,"b"*32})
            self.assertEqual({r["root"] for r in combined["items"]},
                             {str(self.base/"DriveA"/"Movies"),
                              str(self.base/"DriveB"/"Movies")})
            with self.assertRaisesRegex(ValueError,"combined_movie_folder"):
                browser.browse(kind="Movie",category="NotReal")
            with self.assertRaisesRegex(ValueError,"combined_movie_folder"):
                browser.browse(kind="Episode",category="Horror")

    def test_exact_action_finish_skips_new_ja_sidecar(self):
        self.rows[0]["jellyfin_id"]="a"*32
        self.rows[1]["jellyfin_id"]="b"*32
        self.rows[2]["jellyfin_id"]="c"*32
        with mock.patch.object(deep.inventory,"load_latest_manifest",
                               return_value=self.rows):
            selection=finish.selected_media(library_genre="Action",
                                             library_kind="Movie")
            covered=finish.initial_covered(selection)
        self.assertEqual({jid for _,_,jid in selection},
                         {"a"*32,"b"*32})
        self.assertEqual(covered,{"a"*32})
        # The Action queue has exactly one unfinished film.
        self.assertEqual({jid for _,_,jid in selection}-covered,{"b"*32})

    def test_audio_only_is_not_mislabeled_as_subtitled(self):
        self.rows[1]["status"]="japanese_audio"
        with mock.patch.object(browser.coverage,"latest_manifest",
                               return_value=self.manifest):
            self.manifest.write_text(json.dumps({
                "schema":1,"items":self.rows}),encoding="utf-8")
            result=browser.browse(kind="Movie",genre="Action")
        states={x["title"]:x["state"] for x in result["items"]}
        self.assertEqual(states["Crawl"],"audio_only")


if __name__=="__main__":
    unittest.main()
