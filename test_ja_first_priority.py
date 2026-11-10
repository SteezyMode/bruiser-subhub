"""Source priorities: general-purpose across all series, movie genre ordering."""
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

    def test_all_series_get_same_generic_priority(self):
        for name in ("The X-Files", "The X Files",
                     "It's Always Sunny in Philadelphia", "Unrelated Show"):
            self.assertEqual(p.priority({"kind":"Episode","series_title":name}),2)

    def test_no_false_match_based_on_horror_in_film_title(self):
        self.assertEqual(p.priority({"kind":"Movie","title":"Horror Stories",
                                     "host_path":"/media/Movies/Horror.Stories.mkv",
                                     "genres":["Comedy"]}),2)

    def test_search_budget_is_production_scale(self):
        self.assertGreaterEqual(search.MAX_SEARCHES_PER_RUN,500)


if __name__=="__main__":
    unittest.main()
