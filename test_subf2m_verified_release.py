"""SubF2M blank-name recovery: true page evidence, not fabricated title matches."""
from contextlib import contextmanager
from pathlib import Path
import sqlite3
import tempfile
import io
import json
from types import ModuleType, SimpleNamespace
import sys
import unittest
from unittest.mock import patch

from tools import ja_first_stage_sublarr as generic


JID="2eacc0af446f82dde838ffaaec32c6da"
ROW={"jellyfin_id":JID,"kind":"Movie","status":"ready_ja_search",
     "title":"John Wick: Chapter 4","year":2023,
     "host_path":"/mnt/2TB/Plex Expansion/Movies/John.Wick.Chapter.4.2023.mkv"}
CAND={"provider":"subf2m","subtitle_id":"item-1234","language":"ja",
      "filename":".srt","release_info":"","format":"srt","forced":False,
      "kind":"full","grade":"review"}
PROOF={"title":"John Wick: Chapter 4","year":2023,
       "release":"John.Wick.Chapter.4.2023.BDRip.DD5.1.x264-playSD"}


def fake_module(name, **attrs):
    mod=ModuleType(name)
    for key,value in attrs.items():
        setattr(mod,key,value)
    return mod


class SourceProofTests(unittest.TestCase):
    def test_legacy_saved_release_remains_unverified_without_live_proof(self):
        self.assertTrue(generic.subf2m_missing_release(ROW,CAND))
        self.assertFalse(generic.identity_ok(ROW,CAND))
        self.assertTrue(generic.verify_subf2m_proof(ROW,CAND,PROOF))
        with self.assertRaisesRegex(RuntimeError,"unverified_subf2m_source_not_stageable"):
            generic.stage_metadata(ROW,CAND,b"a",1200,
                {"cues":40,"japanese_characters":100,
                 "japanese_cue_fraction":0.95})

    def test_wrong_year_title_or_release_never_qualifies(self):
        for proof in [
            dict(PROOF,year=2014),
            dict(PROOF,title="John Wick: Chapter 3 - Parabellum"),
            dict(PROOF,release="John.Wick.Chapter.3.2019.BDRip"),
            dict(PROOF,release="Some.Other.Movie.2023.WEB-DL"),
            dict(PROOF,release=".srt"),
        ]:
            with self.subTest(proof=proof):
                with self.assertRaises(RuntimeError):
                    generic.verify_subf2m_proof(ROW,CAND,proof)

    def test_legacy_saved_candidates_are_opt_in_until_proven(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"search.sqlite3"
            with sqlite3.connect(path) as db:
                db.execute("CREATE TABLE searches (jellyfin_id TEXT, results_json TEXT)")
                db.execute("INSERT INTO searches VALUES (?,?)",
                           (JID,json.dumps({"candidates":[CAND]})))
            with patch.object(generic.stage,"SEARCH_DB",path), \
                 patch.object(generic.stage,"private_file"):
                self.assertEqual(generic.source_candidates(ROW,provider="subf2m"),[])
                results=generic.source_candidates(
                    ROW,provider="subf2m",include_unverified_subf2m=True)
                self.assertEqual(len(results),1)
                self.assertEqual(results[0]["subtitle_id"],CAND["subtitle_id"])

    def test_forced_and_wrong_language_remain_blocked(self):
        for c in [dict(CAND,language="en"),
                  dict(CAND,forced=True),
                  dict(CAND,kind="signs"),
                  dict(CAND,provider="subdl")]:
            self.assertFalse(generic.subf2m_missing_release(ROW,c))

    def test_saved_release_provenance_must_revalidate_actual_source(self):
        sid,_=generic.remote_identity(CAND)
        qa={"cues":40,"japanese_characters":100,"japanese_cue_fraction":0.95}
        metrics=generic.stage_metadata(ROW,CAND,b"data",1200,qa,proof=PROOF)
        with patch.object(generic,"source_candidates",return_value=[CAND]) as candidates:
            self.assertTrue(generic.validate_staged_provenance(ROW,JID,sid,metrics))
            self.assertTrue(candidates.call_args.kwargs["include_unverified_subf2m"])
            bad=dict(metrics,source_verified_subf2m=dict(PROOF,year=2007))
            with self.assertRaises(RuntimeError):
                generic.validate_staged_provenance(ROW,JID,sid,bad)
            bad=dict(metrics,source_remote_id_sha256="0"*64)
            with self.assertRaises(RuntimeError):
                generic.validate_staged_provenance(ROW,JID,sid,bad)


class ProviderWorkerTests(unittest.TestCase):
    def invoke(self,*,pages=None,listing=None,sub_id="item-1234"):
        seen={"searches":0,"downloads":0,"listings":0}
        if pages is None:
            pages=[{"name":"John Wick: Chapter 4  (2023)",
                    "url":"https://subf2m.co/subtitles/john-wick-chapter-4"},
                   {"name":"John Wick: Chapter 3 - Parabellum (2019)",
                    "url":"https://subf2m.co/subtitles/john-wick-chapter-3-parabellum"}]
        if listing is None:
            listing=[("item-1234","Japanese John.Wick.Chapter.4.2023.BDRip.DD5.1.x264-playSD By sub.Trader"),
                     ("other-id","Japanese John.Wick.Chapter.4.2023.WEB-DL By Anonymous")]
        class FakeLi:
            def __init__(self,slug,text):
                self.slug,self.text=slug,text
            def find(self,name,href=None):
                if name!="a":
                    return None
                return {"href":"/subtitles/john-wick-chapter-4/japanese/"+self.slug}
            def get_text(self,separator=" ",strip=False):
                return self.text
        class FakeSoup:
            def __init__(self,_html,_parser):
                pass
            def select(self,selector):
                assert selector=="li.item"
                return [FakeLi(*x) for x in listing]
        class FakeSession:
            def get(self,url,timeout=None):
                seen["listings"]+=1
                return SimpleNamespace(status_code=200,text="<html></html>")
        class FakeProvider:
            timeout=20
            session=FakeSession()
            def _search_titles(self,title):
                assert title=="John Wick: Chapter 4"
                seen["searches"]+=1
                return pages
        class FakeManager:
            def get_provider(self,provider_name):
                assert provider_name=="subf2m"
                return FakeProvider()
            def search(self,*a,**k):
                seen["downloads"]+=1
                raise AssertionError("Verification must not call manager.search")
        class FakeApp:
            def __init__(self,*a,**k):
                self.config={}
            @contextmanager
            def app_context(self):
                yield
        fake_db=SimpleNamespace(init_app=lambda app:None)
        config=fake_module("config",get_settings=lambda:SimpleNamespace(
            get_database_url=lambda:"sqlite:////config/sublarr.db",database_url=""),
            reload_settings=lambda overrides:None)
        db_module=fake_module("db")
        db_module.__path__=[]
        providers=fake_module("providers",get_provider_manager=lambda:FakeManager())
        providers.__path__=[]
        modules={
            "flask":fake_module("flask",Flask=FakeApp),
            "config":config,
            "extensions":fake_module("extensions",db=fake_db),
            "db":db_module,
            "db.config":fake_module("db.config",get_all_config_entries=lambda:{}),
            "providers":providers,
            "providers.base":fake_module("providers.base",VideoQuery=lambda **kw:kw),
            "bs4":fake_module("bs4",BeautifulSoup=FakeSoup)}
        job={"mode":"verify_subf2m","provider":"subf2m",
             "subtitle_id":sub_id,"filename":".srt","release_info":"",
             "query":{"title":"John Wick: Chapter 4","year":2023}}
        output=io.StringIO()
        with patch.dict(sys.modules,modules), \
             patch.object(sys,"stdin",io.StringIO(json.dumps(job))), \
             patch.object(sys,"stdout",output):
            exec(generic.CONTAINER_WORKER,{"__name__":"__main__"})
        return json.loads(output.getvalue()),seen

    def test_link_is_empty_but_li_text_yields_real_release(self):
        answer,seen=self.invoke()
        self.assertTrue(answer["ok"])
        self.assertFalse(answer["attempted"])
        self.assertEqual(answer["source_proof"],PROOF)
        self.assertEqual(seen["listings"],1)
        self.assertEqual(seen["downloads"],0)

    def test_wrong_year_and_ambiguous_title_pages_hold(self):
        mismatched=[{"name":"John Wick: Chapter 4 (2014)",
                     "url":"https://subf2m.co/subtitles/john-wick-chapter-4"}]
        response,seen=self.invoke(pages=mismatched)
        self.assertFalse(response["ok"])
        self.assertEqual(response["reason"],"unique_title_year_page_not_verified")
        self.assertEqual(seen["listings"],0)
        duplicated=[{"name":"John Wick: Chapter 4 (2023)",
                     "url":"https://subf2m.co/subtitles/john-wick-chapter-4"}]*2
        response,_=self.invoke(pages=duplicated)
        self.assertFalse(response["ok"])

    def test_wrong_release_or_subtitle_id_holds_no_download(self):
        for kwargs in [
            {"sub_id":"not-from-page"},
            {"listing":[("item-1234","Japanese Other.Movie.2023.WEB-DL By Other")]},
            {"listing":[("item-1234","Japanese By Anonymous")]},
        ]:
            with self.subTest(kwargs=kwargs):
                result,seen=self.invoke(**kwargs)
                self.assertFalse(result["ok"])
                self.assertFalse(result["attempted"])
                self.assertEqual(seen["downloads"],0)


if __name__=="__main__":
    unittest.main()
