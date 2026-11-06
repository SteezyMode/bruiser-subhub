"""Fail-closed Japanese source planning for untagged original audio.

Fixtures only: no Jellyfin, Docker, network, provider usage, or media writes.
"""
from pathlib import Path
import tempfile
import unittest

from tools import ja_first_catalog_manifest as catalog
from tools import ja_first_search_pilot as search


class AudioLanguageGateTests(unittest.TestCase):
    def test_catalog_untagged_audio_is_review_not_japanese_search(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            video=root/"Trick.S01E01.mkv"
            video.write_bytes(b"synthetic")
            item={
                "Type":"Movie","Id":"example-jellyfin-id","Name":"Trick",
                "Path":str(video),"ProviderIds":{"imdb":"tt0123456"},
                "MediaStreams":[{"Type":"Audio","Language":"und",
                                 "IsDefault":True}],
            }
            mounts=[(root,Path("/media/bigdisk-video"))]
            state=catalog.classify(item,{},mounts,{})
            self.assertEqual(state["status"],"review_audio_language_unverified")
            self.assertEqual(state["audio_language"],"und")
            self.assertNotEqual(state["status"],"ready_ja_search")
            for label in ("", "unknown", "mul", "zxx", "none"):
                item["MediaStreams"][0]["Language"]=label
                state=catalog.classify(item,{},mounts,{})
                self.assertEqual(state["status"],"review_audio_language_unverified")

    def test_catalog_verified_audio_keeps_normal_routing(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            video=root/"Example.mkv"
            video.write_bytes(b"synthetic")
            item={
                "Type":"Movie","Id":"example-jellyfin-id","Name":"Example",
                "Path":str(video),"ProviderIds":{"imdb":"tt0123456"},
                "MediaStreams":[{"Type":"Audio","Language":"eng",
                                 "IsDefault":True}],
            }
            mounts=[(root,Path("/media/bigdisk-video"))]
            self.assertEqual(catalog.classify(item,{},mounts,{})["status"],
                             "ready_ja_search")
            item["MediaStreams"][0]["Language"]="jpn"
            self.assertEqual(catalog.classify(item,{},mounts,{})["status"],
                             "japanese_audio")
            item["MediaStreams"][0]["Language"]="eng"
            item["MediaStreams"].append({"Type":"Subtitle","Language":"jpn",
                                         "IsForced":False})
            self.assertEqual(catalog.classify(item,{},mounts,{})["status"],
                             "existing_japanese_subtitle")

    def test_saved_old_manifest_cannot_search_untagged_audio(self):
        with tempfile.TemporaryDirectory() as folder:
            video=Path(folder)/"Trick.S01E01.mkv"
            video.write_bytes(b"synthetic")
            row={
                "status":"ready_ja_search",
                "host_path":str(video),
                "kind":"Episode","series_title":"Trick",
                "season":1,"episode":1,
            }
            for lang in ("unknown","und","",None,"jpn","ja-JP","mul"):
                row["audio_language"]=lang
                self.assertIsNone(search.query_for(row))
            row["audio_language"]="eng"
            self.assertIsNotNone(search.query_for(row))
            row["audio_language"]="fra"
            self.assertIsNotNone(search.query_for(row))


if __name__ == "__main__":
    unittest.main()
