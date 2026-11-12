"""Offline checks for genre browsing and the movie-only full source scope."""
import unittest
from tools import subhub_media_categories as categories
from tools import ja_first_movie_scope as scope


class UnifiedCategories(unittest.TestCase):
    def test_one_action_category_for_both_drives(self):
        a=categories.categories("Movie",
            "/mnt/2TB/Plex Expansion/Movies/Action/FilmA.mkv",["Action"])
        b=categories.categories("Movie",
            "/mnt/BigDisk/Video/Movies/ACTION/FilmB.mkv",["Action"])
        self.assertEqual([x.casefold() for x in a],["action"])
        self.assertEqual([x.casefold() for x in b],["action"])

    def test_tv_documentary_comes_from_genre_or_existing_folder(self):
        self.assertEqual(categories.categories("Episode",
            "/mnt/2TB/Television/Documentaries/Nature/S01E01.mkv",[]),
            ["Documentary"])
        self.assertEqual(categories.categories("Episode",
            "/mnt/BigDisk/Television/Episodic/Nature/S01E01.mkv",
            ["Documentaries"]),["Documentary"])

    def test_horror_and_drama_full_pass_is_movies_only_across_both_drives(self):
        films=[
            {"kind":"Movie","host_path":
             "/mnt/2TB/Plex Expansion/Movies/Horror/FilmA.mkv","genres":[]},
            {"kind":"Movie","host_path":
             "/mnt/BigDisk/Video/Movies/Action/FilmB.mkv",
             "genres":["Drama","Action"]},
            {"kind":"Movie","host_path":
             "/mnt/BigDisk/Video/Movies/Drama/FilmC.mkv","genres":[]},
        ]
        self.assertTrue(all(scope.matches(x,"horror-drama-folders") for x in films))
        self.assertFalse(scope.matches({
            "kind":"Movie","host_path":
            "/mnt/2TB/Plex Expansion/Movies/Action/FilmD.mkv",
            "genres":["Action"]},"horror-drama-folders"))
        self.assertFalse(scope.matches({
            "kind":"Episode","host_path":
            "/mnt/2TB/Television/Horror/Show/S01E01.mkv",
            "genres":["Horror"]},"horror-drama-folders"))

    def test_adding_documentary_does_not_automatically_pick_tv(self):
        movie=categories.categories("Movie",
            "/mnt/BigDisk/Video/Movies/Horror/Nature.mkv",
            ["Documentary"])
        self.assertIn("Documentary",movie)
        tv=categories.categories("Episode",
            "/mnt/BigDisk/Television/Episodic/Docs/S01E01.mkv",[])
        self.assertEqual(tv,["Other Television"])


if __name__=="__main__":
    unittest.main()
