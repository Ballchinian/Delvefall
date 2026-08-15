#the sitemap is a sitemapindex over four parts, and the three card parts are
#rank bands. the bands are the whole point (google reports coverage per file, so
#split they diagnose where indexing stops rather than just how much of it there
#is), but a band is also the one thing here that can go silently wrong: a gap
#between two of them drops real cards out of the sitemap and nothing raises.
#
#so these lock the arithmetic rather than the xml. no database: the tiers are
#constants and the sql that reads them is exercised against a live pool

from views.meta import CARD_TIERS, CARD_TIER_BY_KEY, SITEMAP_KEYS, urlset


class TestTheBands:

    def test_the_bands_are_contiguous(self):
        #a gap here is a card in no sitemap at all
        for earlier, later in zip(CARD_TIERS, CARD_TIERS[1:]):
            assert earlier["hi"] is not None, "only the last band may be open ended"
            assert later["lo"] == earlier["hi"] + 1

    def test_the_bands_start_at_the_top_and_never_overlap(self):
        assert CARD_TIERS[0]["lo"] == 1
        for tier in CARD_TIERS:
            assert tier["hi"] is None or tier["lo"] <= tier["hi"]

    def test_the_last_band_is_open_ended(self):
        #it has to be, or a card ranked past it is in no sitemap. it is also the
        #one that carries the unranked
        assert CARD_TIERS[-1]["hi"] is None

    def test_every_key_is_distinct(self):
        keys = [t["key"] for t in CARD_TIERS]
        assert len(keys) == len(set(keys))
        assert set(CARD_TIER_BY_KEY) == set(keys)


class TestTheIndex:

    def test_the_index_names_the_pages_part_and_every_band(self):
        assert SITEMAP_KEYS == ["pages"] + [t["key"] for t in CARD_TIERS]

    def test_no_key_collides_with_the_pages_part(self):
        #"/sitemap-pages.xml" is answered before the bands are consulted, so a
        #band called pages would be unreachable
        assert "pages" not in CARD_TIER_BY_KEY


class TestTheLastmod:
    #the field's trust is binary: a stand-in date on a url nothing knows about
    #gets every date in the file discounted, so silence has to survive refactors

    def test_a_dated_url_carries_its_lastmod(self):
        out = "".join(urlset([("https://delvefall.com/search?q=Bolt", "2026-08-15")]))
        assert "<lastmod>2026-08-15</lastmod>" in out

    def test_an_undated_url_carries_nothing(self):
        out = "".join(urlset([("https://delvefall.com/guide", None)]))
        assert "lastmod" not in out
        assert "<url><loc>https://delvefall.com/guide</loc></url>" in out

    def test_one_missing_date_does_not_borrow_its_neighbour(self):
        #the failure that matters: a loop carrying the last date forward would
        #stamp the whole tail with one day
        out = "".join(urlset([("https://delvefall.com/a", "2026-08-15"),
                              ("https://delvefall.com/b", None)]))
        assert out.count("<lastmod>") == 1
        assert "<url><loc>https://delvefall.com/b</loc></url>" in out
