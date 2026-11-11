"""Offline regression for read-only Jellyfin subtitle GET pilot."""
import io
import json
import unittest
from types import SimpleNamespace

from tools import probe_jellyfin_remote_subtitle as probe


class MemoryResponse(io.BytesIO):
    def __init__(self, data, content_type="application/octet-stream"):
        super().__init__(data)
        self.headers={"Content-Type":content_type}


class FakeOpener:
    def __init__(self, body, *, ct="application/octet-stream"):
        self.body=body
        self.ct=ct
        self.calls=[]
    def open(self,request,timeout):
        self.calls.append(request)
        assert timeout==100
        return MemoryResponse(self.body,self.ct)


class RemoteSubtitleProbeTests(unittest.TestCase):
    def setUp(self):
        self.episode={"kind":"Episode","series_title":"It's Always Sunny in Philadelphia",
                      "season":7,"episode":2,"jellyfin_id":"a"*32}
        self.correct={"Id":"subbuzz_subtitle:23231","ProviderName":"subbuzz",
                      "Name":"Its.Always.Sunny.in.Philadelphia.S07E02.WEB-DL.DSNP.ja",
                      "ThreeLetterISOLanguageName":"jpn","Format":"srt"}

    def test_exact_title_and_episode_accepts_its_apostrophe_normalization(self):
        self.assertTrue(probe.relevant(self.episode,self.correct))
        invalid=dict(self.correct,Name="Its.Always.Sunny.in.Philadelphia.S07E03.ja")
        self.assertFalse(probe.relevant(self.episode,invalid))
        wrong=dict(self.correct,Name="Other.Show.S07E02.ja")
        self.assertFalse(probe.relevant(self.episode,wrong))
        non_japanese=dict(self.correct,ThreeLetterISOLanguageName="eng")
        self.assertFalse(probe.relevant(self.episode,non_japanese))

    def test_no_remote_post_and_auth_stays_local(self):
        op=FakeOpener(json.dumps([self.correct]).encode(),ct="application/json")
        items=probe.request_candidates(self.episode,"SECRET",op)
        self.assertEqual(items,[self.correct])
        self.assertEqual(len(op.calls),1)
        req=op.calls[0]
        self.assertEqual(req.get_method(),"GET")
        self.assertEqual(req.full_url,"http://127.0.0.1:8096/Items/"+"a"*32+
                         "/RemoteSearch/Subtitles/ja")
        self.assertEqual(req.get_header("Authorization"),"SECRET")

    def test_remote_subtitle_fetched_into_memory_only(self):
        srt=("1\n00:00:01,000 --> 00:00:02,000\nこんにちは世界！\n\n"
             "2\n00:00:03,000 --> 00:00:04,000\nありがとうございまーす。\n")
        raw=srt.encode()
        op=FakeOpener(raw,ct="application/x-subrip")
        data,ct=probe.get_remote_bytes(self.correct,"SECRET",op)
        self.assertEqual(data,raw)
        self.assertEqual(op.calls[0].get_method(),"GET")
        self.assertTrue(op.calls[0].full_url.startswith(
            "http://127.0.0.1:8096/Providers/Subtitles/Subtitles/"))
        self.assertEqual(op.calls[0].get_header("Authorization"),"SECRET")
        summary=probe.characterize(data,ct)
        self.assertEqual(summary["timed_cues"],2)
        self.assertTrue(summary["looks_like_timed_japanese"])
        self.assertNotIn("こんにちは",json.dumps(summary,ensure_ascii=False))
        self.assertNotIn("SECRET",json.dumps(summary))

    def test_refuse_oversize_content_or_missing_id(self):
        op=FakeOpener(b"a"*(probe.MAX_SUB_BYTES+1))
        with self.assertRaisesRegex(RuntimeError,"oversize"):
            probe.get_remote_bytes(self.correct,"TOKEN",op)
        with self.assertRaises(ValueError):
            probe.get_remote_bytes({"Id":""},"TOKEN",FakeOpener(b"any"))

    def test_redirect_refused(self):
        with self.assertRaisesRegex(RuntimeError,"redirect_not_allowed"):
            probe.NoRedirect().redirect_request(None,None,302,"found",{},
                                                "http://evil.example/")

    def test_movie_wrong_year_and_wrong_title_fail(self):
        movie={"kind":"Movie","title":"Bride of Chucky","year":1998}
        self.assertTrue(probe.relevant(movie,{
            "Name":"Bride.Of.Chucky.1998.WEB-DL.ja","ThreeLetterISOLanguageName":"jpn"}))
        self.assertFalse(probe.relevant(movie,{
            "Name":"Bride.Of.Re-Animator.1990.ja","ThreeLetterISOLanguageName":"jpn"}))
        self.assertFalse(probe.relevant(movie,{
            "Name":"Bride.Of.Chucky.2008.ja","ThreeLetterISOLanguageName":"jpn"}))


if __name__=="__main__":
    unittest.main()
