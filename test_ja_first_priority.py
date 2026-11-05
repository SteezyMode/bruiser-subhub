"""Source priorities: user-requested films/shows first, all others still eligible."""
import unittest
from tools import ja_first_priority as p
from tools import ja_first_search_pilot as search


class PriorityTests(unittest.TestCase):
    def test_horror_and_drama_movies_precede_ordinary_movies(self):
        horror={"kind":"Movie","title":"Baskin",
                "genres":["Horror"],"host_path":"/library/Movies/Baskin.mkv"}
        drama={"kind":"Movie","title":"Fargo",
               "genres":[],"host_path":"/mnt/BigDisk/Video/Movies/Drama, Suspense/Fargo.mkv"}
        other={"kind":"Movie","title":"Comedy","genres":["Comedy"],
               "host_path":"/library/Movies/Comedy.mkv"}
        self.assertLess(p.priority(horror),p.priority(drama))
        self.assertLess(p.priority(drama),p.priority(other))

    def test_x_files_and_sunny_prioritized_without_episode_overrides(self):
        self.assertEqual(p.priority({"kind":"Episode","series_title":"The X-Files"}),0)
        self.assertEqual(p.priority({"kind":"Episode","series_title":"The X Files"}),0)
        self.assertEqual(p.priority({"kind":"Episode",
                                     "series_title":"It's Always Sunny in Philadelphia"}),0)
        self.assertGreater(p.priority({"kind":"Episode",
                                        "series_title":"Unrelated Show"}),0)

    def test_no_false_match_based_on_horror_in_film_title(self):
        self.assertEqual(p.priority({"kind":"Movie","title":"Horror Stories",
                                     "host_path":"/media/Movies/Horror.Stories.mkv",
                                     "genres":["Comedy"]}),2)

    def test_search_budget_is_production_scale(self):
        self.assertGreaterEqual(search.MAX_SEARCHES_PER_RUN,500)


if __name__=="__main__":
    unittest.main()
