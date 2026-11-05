"""Host publishing mount/copy-only safety tests, offline."""
import tempfile
import unittest
from pathlib import Path
from tools import bruiser_ja_publish_host as bridge

class TestHostPublish(unittest.TestCase):
    def test_longest_bind_mapping_and_ro_container_ok(self):
        with tempfile.TemporaryDirectory() as t:
            src=Path(t)/'source'
            folder=src/'Movies'/'Drama'
            folder.mkdir(parents=True)
            video=folder/'Example.2017.mp4'
            video.write_bytes(b'original video')
            mounts=[
                {'Type':'bind','Source':str(Path(t)/'other'),'Destination':'/media'},
                {'Type':'bind','Source':str(src),'Destination':'/media/bigdisk-video','RW':False}
            ]
            output=bridge.host_path_for_movie(mounts,'/media/bigdisk-video/Movies/Drama/Example.2017.mp4')
            self.assertEqual(output,video)
            self.assertEqual(video.read_bytes(),b'original video')

    def test_create_only_copied_sidecar_and_refuse_overwrite(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t)
            video=root/'Example.2017.mp4'
            video.write_bytes(b'original video')
            aligned=root/'alignment.srt'
            aligned.write_bytes(b'1\n00:00:01,000 --> 00:00:03,000\n\xe6\x97\xa5\xe6\x9c\xac\xe8\xaa\x9e\n')
            result=bridge.publish_from_copy(video,aligned,apply=False)
            self.assertIsNone(result)
            self.assertFalse(list(root.glob('*.ja.srt')))
            result=bridge.publish_from_copy(video,aligned,apply=True)
            self.assertEqual(result.read_bytes(),aligned.read_bytes())
            self.assertEqual(video.read_bytes(),b'original video')
            with self.assertRaises(RuntimeError):
                bridge.publish_from_copy(video,aligned,apply=True)

    def test_existing_editorial_japanese_blocks_publish(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t)
            video=root/'Example.2017.mp4'
            video.write_bytes(b'original video')
            (root/'Example.2017.Curated.ja.srt').write_text('untouched')
            aligned=root/'aligned.srt'
            aligned.write_bytes(b'saved staged subtitle')
            with self.assertRaises(RuntimeError):
                bridge.publish_from_copy(video,aligned,apply=True)
            self.assertFalse((root/('Example.2017'+bridge.TARGET_SUFFIX)).exists())

    def test_reject_path_traversal_no_matching_mount(self):
        with self.assertRaises(RuntimeError):
            bridge.host_path_for_movie([],'/media/../etc/passwd')

if __name__=='__main__': unittest.main()
