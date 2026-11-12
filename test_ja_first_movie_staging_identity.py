"""Real historical source identities: staging eligibility, not publication trust."""
import unittest
from tools import ja_first_stage_saved_batch as stage
from tools import ja_first_stage_subdl as subdl


def case(title,year,release,provider="opensubtitles",language="ja",extra=None):
    row={"kind":"Movie","title":title,"year":year}
    c={"provider":provider,"subtitle_id":
       "123456" if provider=="opensubtitles" else "3746725-8668631",
       "language":language,"filename":release}
    if extra: c.update(extra)
    return row,c


class MovieStagingIdentityRegressions(unittest.TestCase):
    def test_one_year_festival_or_release_difference_is_stageable_only(self):
        for title,year,release in [
            ("Green Room",2016,"Green.Room.2015.720p.BluRay.x264_ja"),
            ("Late Night with the Devil",2024,
             "Late.Night.with.the.Devil.2023.WEB-DL.ja-JP"),
            ("The Witch",2016,"The.Witch.2015.WEB-DL.ja"),
            ("Stopmotion",2024,"Stopmotion.2023.1080p.AMZN.WEB-DL"),
            ("Ghost Stories",2018,"Ghost_Stories.2017.1080p"),
            ("The Rule of Jenny Pen",2025,
             "The.Rule.of.Jenny.Pen.2024.1080p.WEB-DL.ja.srt"),
            ("In the Mouth of Madness",1995,
             "In_the_Mouth_of_Madness_1994_1080p_BluRay"),
        ]:
            with self.subTest(title=title):
                row,c=case(title,year,release)
                self.assertTrue(stage.identity_ok(row,c))

    def test_subdl_uses_same_explicit_full_title_year_rule(self):
        for title,year,release in [
            ("Double Blind",2024,
             "Double.Blind.2023.1080p.AMZN.WEB-DL.ja.srt"),
            ("The Rule of Jenny Pen",2025,
             "The.Rule.of.Jenny.Pen.2024.1080p.AMZN.WEB-DL.ja.srt")]:
            with self.subTest(title=title):
                row,c=case(title,year,release,provider="subdl")
                self.assertTrue(subdl.identity_ok(row,c))
                c["filename"]="She.Hulk.2024.ja.srt"
                self.assertFalse(subdl.identity_ok(row,c))

    def test_exact_japanese_suffix_without_year(self):
        for title,year,release in [
            ("[REC]",2007,"Recjp"),
            ("Blue Ruin",2014,"Blue.Ruin-jpa"),
            ("Lost Highway",1997,"Lost_Highwayjp"),
            ("Skinamarink",2023,"Skinamarinkjp"),
            ("V/H/S",2012,"VHS_JP"),
        ]:
            with self.subTest(title=title):
                row,c=case(title,year,release)
                self.assertTrue(stage.identity_ok(row,c))

    def test_exact_short_title_year_but_not_similar_titles(self):
        row,c=case(
            "Borat: Cultural Learnings of America for Make Benefit Glorious Nation of Kazakhstan",
            2006,"Borat.2006.720p.BrRip.x264")
        self.assertTrue(stage.identity_ok(row,c))
        for release in ("Nymphomaniac.Vol.I.2013.LIMITED.720p",
                        "Nymphomaniac.Vol.II.2013"):
            row,c=case("Maniac",1980,release)
            self.assertFalse(stage.identity_ok(row,c))

    def test_conflicting_years_or_wrong_language_are_rejected(self):
        for title,year,release in [
            ("Green Room",2016,"Green.Room.2012.BluRay.ja"),
            ("The Witch",2016,"The.Witch.2021.WEB-DL"),
            ("Funny Games",2008,
             "Funny.Games.2007.1080p.BluRay.x265.HEVC.10bit.AAC.5.1.Tigole-QxR.eng"),
            ("A Fistful of Dollars",1964,"1964"),
            ("The Cat Returns",2002,"Neko_No_Ongaeshi_2002.07.19"),
            ("The Platform",2019,"El_Hoyo_Japanese"),
            ("Ride the High Country",1962,
             "she-hulk-attorney-at-law-first-season_japanese-2880486.zip"),
        ]:
            with self.subTest(title=title):
                row,c=case(title,year,release)
                self.assertFalse(stage.identity_ok(row,c))

    def test_not_spoofed_by_substring_or_sequel(self):
        for title,year,release in [
            ("[REC]",2007,"Rec2jp"),
            ("Borat",2006,"Borat.Subsequent.Moviefilm.2020"),
            ("The Witch",2016,"The.Witch.2010.WEB-DL.ja"),
            ("Maniac",1980,"Nymphomaniac.1980.ja"),
        ]:
            with self.subTest(title=title):
                row,c=case(title,year,release)
                self.assertFalse(stage.identity_ok(row,c))
        row,c=case("Green Room",2016,"Green.Room.2015.BluRay",language="en")
        self.assertFalse(stage.identity_ok(row,c))


if __name__=="__main__":
    unittest.main()
