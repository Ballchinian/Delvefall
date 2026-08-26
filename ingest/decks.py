#mtgjson's precons into decks + deck_cards, the calibration set for deck
#originality: a score is not a readable sentence, "more original than every
#precon but two" is, and that needs a fair population to sit against. precons are
#it, every one being 100 singleton cards built to the same brief.
#    python -m ingest.decks
#with DATABASE_URL set. reruns are free, the meta gate skipping the work unless
#mtgjson published a newer version.
#
#NO NAME MATCHING: mtgjson carries identifiers.scryfallOracleId on every card, so
#the join is exact. on the 2026-07-22 file, 6254 of 6257 distinct precon cards
#land in our table and 6248 of those already carry a uniqueness score

import os
import sys
import time

import psycopg
import requests

from common.cards import HEADERS
from ingest.update import get_with_retries

DECKLIST_URL = "https://mtgjson.com/api/v5/DeckList.json"
DECK_URL = "https://mtgjson.com/api/v5/decks/%s.json"

#nothing reads the string, it is a MARKER: change it whenever this starts filling
#a column it did not before, and the gate in main() forces exactly one rebuild to
#go and get it
DECK_FIELDS = "source source_ok"

#mtgjson publishes 2990 decks across theme decks, jumpstart, secret lair drops
#and mtgo redemption piles. none are 100 card singleton commander decks, so none
#are comparable to a pasted list, which is the whole point of the table
DECK_TYPE = "Commander Deck"

#one file per deck and about 190 of them, the one place in the pipeline making a
#lot of small requests
REQUEST_PAUSE = 0.1


#ONLY a 404 or a 410 takes a link away. magic.wizards.com sits behind a bot
#filter that answers 403 to most of these, and a check counting every non-200 as
#dead would have blanked 83 of the 155 working links the first time it ran. a 403
#is the filter talking, a 404 is the site. anything else, a timeout included,
#leaves the link alone
DEAD_CODES = (404, 410)

#one a second, ten times slower than the deck downloads above: the filter answers
#more honestly the slower you go, and 65 distinct urls is about a minute
SOURCE_PAUSE = 1.0


def dead_sources(urls):
    #HEAD, so this is 65 status lines rather than 65 articles
    session = requests.Session()
    session.headers.update(HEADERS)
    dead = set()
    for url in sorted(urls):
        try:
            code = session.head(url, timeout=30, allow_redirects=True).status_code
        except Exception as e:
            print("  unreachable, keeping the link: " + url + " (" + str(e) + ")")
            continue
        if code in DEAD_CODES:
            dead.add(url)
            print("  " + str(code) + " " + url)
        time.sleep(SOURCE_PAUSE)
    return dead


def fetch_decks(entries):
    #a deck that fails to download is skipped rather than fatal, 189 of 190
    #calibrating fine. the misses come back WITH the decks because main() holds
    #the version marker back when the list is short: a marker written over an
    #incomplete run leaves the board a deck down until mtgjson publishes again
    session = requests.Session()
    session.headers.update(HEADERS)
    out = {}
    missed = []
    for i, entry in enumerate(entries):
        slug = entry["fileName"]
        #three goes, like get_with_retries does for every other request here.
        #a straggler is nearly always one timeout rather than a missing file
        for attempt in range(3):
            try:
                r = session.get(DECK_URL % slug, timeout=60)
                r.raise_for_status()
                out[slug] = r.json()["data"]
                break
            except Exception as e:
                if attempt == 2:
                    print("  skipped " + slug + " (" + str(e) + ")")
                    missed.append(slug)
                else:
                    time.sleep(2 * (attempt + 1))
        if i and i % 50 == 0:
            print("  " + str(i) + "/" + str(len(entries)) + "...")
        time.sleep(REQUEST_PAUSE)
    return out, missed


def deck_cards(deck):
    #counts are kept because a deck is not 100 distinct cards, it is 63 spells
    #and 37 lands. the ORIGINALITY query ignores them and reads distinct rows,
    #nine Islands saying nothing about a deck's ideas that one Island does not
    leaders = {c.get("identifiers", {}).get("scryfallOracleId")
               for c in deck.get("commander", [])}
    seen = {}
    for card in deck.get("mainBoard", []) + deck.get("commander", []):
        oid = card.get("identifiers", {}).get("scryfallOracleId")
        if not oid:
            continue
        #the same card can appear in both boards, and the primary key on
        #(deck, oracle_id) means the copies are summed here, not inserted twice
        if oid in seen:
            seen[oid]["count"] += card.get("count", 1)
        else:
            seen[oid] = {"count": card.get("count", 1), "commander": oid in leaders}
    return [(oid, v["count"], v["commander"]) for oid, v in seen.items()]


def drop_reprint_editions(decks):
    #collector's editions are the same 100 cards in a different treatment, listed
    #separately: 16 of the 190 on the 2026-07-22 file. left in they count twice
    #in every average and hand the leaderboard duplicate rows.
    #
    #the CARD SET is the identity, and the shorter name wins because "Tyranid
    #Swarm" is the deck and "Tyranid Swarm Collector's Edition" is a product
    keep = {}
    for slug in sorted(decks, key=lambda s: (len(decks[s]["name"]), s)):
        fingerprint = tuple(sorted(oid for oid, _, _ in decks[slug]["cards"]))
        if fingerprint in keep:
            continue
        keep[fingerprint] = slug
    return {slug: decks[slug] for slug in keep.values()}


def main():
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("set DATABASE_URL first (the postgres connection string)")
        sys.exit(1)

    conn = psycopg.connect(db_url)
    schema_path = os.path.join(os.path.dirname(__file__), "..", "common", "schema.sql")
    with open(schema_path, encoding="utf-8") as f:
        conn.execute(f.read())
    conn.commit()

    print("asking mtgjson for the deck list...")
    listing = get_with_retries(DECKLIST_URL).json()
    version = listing["meta"]["version"]

    #the same gate as the tag ingest, and an empty deck_cards means a first run
    #or one that died halfway.
    #
    #DECK_FIELDS is what forces the single rerun a new column needs: schema.sql
    #adds it empty, mtgjson's version has not moved, and without this it stays
    #empty until mtgjson happens to publish. it asks the MARKER, not the data.
    #"is any deck's source empty?" reads like the same question, but the day
    #mtgjson ships one Commander deck with no source the answer is yes forever
    #and this redownloads all 190 files nightly for nothing
    row = conn.execute("SELECT value FROM meta WHERE key = 'mtgjson_version'").fetchone()
    fields = conn.execute("SELECT value FROM meta WHERE key = 'mtgjson_deck_fields'").fetchone()
    if (row and row[0] == version
            and fields and fields[0] == DECK_FIELDS
            and conn.execute("SELECT 1 FROM deck_cards LIMIT 1").fetchone()):
        print("already processed mtgjson " + version + ", nothing to do")
        conn.close()
        return

    entries = [d for d in listing["data"] if d["type"] == DECK_TYPE]
    print("mtgjson " + version + " lists " + str(len(entries)) + " " + DECK_TYPE + "s, downloading...")
    raw, missed = fetch_decks(entries)

    decks = {}
    for slug, deck in raw.items():
        decks[slug] = {
            "name": deck["name"],
            "code": deck.get("code", ""),
            "date": deck.get("releaseDate"),
            "type": deck.get("type", DECK_TYPE),
            "source": deck.get("source") or "",
            "cards": deck_cards(deck),
        }
    before = len(decks)
    decks = drop_reprint_editions(decks)
    print("got " + str(before) + " decks, " + str(len(decks)) + " after dropping reprint editions")

    #BEFORE the transaction below and before the truncate inside it: this is a
    #minute of requests and it must not run holding a lock on the board.
    #
    #once dead, STAYS dead, which is what reading the old column back buys. the
    #bot filter means a url that 404s today can answer 403 tomorrow, and without
    #carrying the answer forward the same link would appear and vanish from the
    #board on alternate ingests. the cost is that a page wizards restores stays
    #hidden until someone clears the flag by hand, which for a section they
    #deleted years ago is the right way round.
    #fragments are dropped for the check because the server never sees one: four
    #of the tarkir lists are the same article with a different anchor
    was_dead = {r[0].split("#")[0] for r in
                conn.execute("SELECT source FROM decks WHERE NOT source_ok AND source <> ''")}
    urls = {d["source"].split("#")[0] for d in decks.values() if d["source"]}
    print("checking " + str(len(urls - was_dead)) + " source urls ("
          + str(len(was_dead)) + " already known dead)...")
    dead = was_dead | dead_sources(urls - was_dead)
    print(str(len(dead)) + " of " + str(len(urls)) + " source urls lead nowhere")

    #a card we do not have cannot be scored and the foreign key would refuse the
    #row anyway. dropping it quietly is right: 3 of 6257 measured, and they are
    #cards our own ingest chose not to keep rather than gaps in mtgjson
    known = {str(r[0]) for r in conn.execute("SELECT oracle_id FROM cards")}

    with conn.cursor() as cur:
        #the cascade clears deck_cards with it
        cur.execute("TRUNCATE decks CASCADE")
        missing = 0
        card_rows = []
        for slug, d in decks.items():
            cur.execute("""INSERT INTO decks (slug, name, code, release_date, type, source, source_ok)
                           VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                        (slug, d["name"], d["code"], d["date"], d["type"], d["source"],
                         d["source"].split("#")[0] not in dead))
            for oid, count, commander in d["cards"]:
                if oid not in known:
                    missing += 1
                    continue
                card_rows.append((slug, oid, count, commander))
        #the deck rows go one at a time above, each having to land before its
        #cards can point at it. the cards are 16k and go together
        cur.executemany("""INSERT INTO deck_cards (deck_slug, oracle_id, count, is_commander)
                           VALUES (%s, %s, %s, %s)""", card_rows)
        rows = len(card_rows)
        #the version marker only goes in when EVERY deck landed, that being the
        #whole claim it makes. the cost of leaving it out is tomorrow
        #redownloading all 190 files, twenty seconds of small requests next to
        #the two gigabytes this workflow already pulls. a file broken at
        #mtgjson's end repeats that nightly, which is the right way round: the
        #log names the deck every time instead of the board quietly being wrong
        if missed:
            print("NOT recording the version: " + str(len(missed))
                  + " deck(s) did not download, so tomorrow will try them again")
        else:
            cur.execute("""INSERT INTO meta (key, value) VALUES ('mtgjson_version', %s)
                           ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value""", (version,))
        #same transaction as the rows it describes, so a run that dies halfway
        #leaves neither and the next one does the work again
        cur.execute("""INSERT INTO meta (key, value) VALUES ('mtgjson_deck_fields', %s)
                       ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value""", (DECK_FIELDS,))
    conn.commit()
    print("wrote " + str(len(decks)) + " decks and " + str(rows) + " deck cards")
    if missing:
        print("(" + str(missing) + " card slots had no matching card in our table)")
    conn.close()


if __name__ == "__main__":
    main()
