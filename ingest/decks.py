#pulls the preconstructed commander decks from mtgjson into decks + deck_cards.
#they are the calibration set for deck originality: a single deck's score is
#not a sentence anyone can read, "more original than every precon but two" is,
#and that comparison needs a fair population to sit against. precons are it,
#every one of them is 100 singleton cards built to the same brief.
#run it from the repo root like the updater:
#    python -m ingest.decks
#with DATABASE_URL set. reruns are free: the meta gate skips the work unless
#mtgjson published a newer version.
#
#no scryfall involvement and no name matching: mtgjson carries
#identifiers.scryfallOracleId on every card in every deck, which is the same
#key cards is built on, so the join is exact. measured on the 2026-07-22 file,
#6254 of 6257 distinct precon cards land in our table and 6248 of those already
#carry a uniqueness score

import os
import sys
import time

import psycopg
import requests

from common.cards import HEADERS
from ingest.update import get_with_retries

DECKLIST_URL = "https://mtgjson.com/api/v5/DeckList.json"
DECK_URL = "https://mtgjson.com/api/v5/decks/%s.json"

#which of mtgjson's per-deck fields this script copies across. nothing reads
#the string, it is a marker: change it whenever this starts filling a column
#it did not fill before, and the gate in main() forces exactly one rebuild to
#go and get it
DECK_FIELDS = "source"

#the only deck type worth having. mtgjson publishes 2990 decks across theme
#decks, jumpstart, secret lair drops and mtgo redemption piles, none of which
#are 100 card singleton commander decks and so none of which are comparable to
#a pasted list. that comparability is the whole point of the table
DECK_TYPE = "Commander Deck"

#mtgjson serves one file per deck and we want about 190 of them, so this is
#the one place in the pipeline that makes a lot of small requests. a shared
#session keeps it to one connection and the pause keeps it neighbourly
REQUEST_PAUSE = 0.1


def fetch_decks(entries):
    #one file per deck, keyed by the mtgjson fileName. a deck that fails to
    #download is skipped rather than fatal: 189 of 190 still calibrates fine.
    #
    #returns (decks, missed) because the CALLER has to know, and for a while it
    #did not. this was the only fetch in the pipeline with no retry at all, so
    #one blip dropped a deck, and the version marker then went in as though the
    #run had been complete. the gate reads that marker, so the next run said
    #"already processed" and the board sat a deck short until mtgjson happened
    #to publish a new version. the comment here promised the opposite
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
    #the cards in one deck as (oracle_id, count, is_commander). counts are kept
    #because a deck is not 100 distinct cards, it is 63 spells and 37 lands, and
    #anything measuring the mana base later will want to know. the ORIGINALITY
    #query does not use them: nine Islands say nothing about a deck's ideas that
    #one Island does not, so it reads distinct rows
    leaders = {c.get("identifiers", {}).get("scryfallOracleId")
               for c in deck.get("commander", [])}
    seen = {}
    for card in deck.get("mainBoard", []) + deck.get("commander", []):
        oid = card.get("identifiers", {}).get("scryfallOracleId")
        if not oid:
            continue
        #the same card can appear in both boards, and a primary key on
        #(deck, oracle_id) means the copies have to be summed here rather
        #than inserted twice
        if oid in seen:
            seen[oid]["count"] += card.get("count", 1)
        else:
            seen[oid] = {"count": card.get("count", 1), "commander": oid in leaders}
    return [(oid, v["count"], v["commander"]) for oid, v in seen.items()]


def drop_reprint_editions(decks):
    #collector's edition decks are the same 100 cards in a different treatment,
    #and mtgjson lists them separately: 16 of the 190 on the 2026-07-22 file.
    #left in they would count twice in every average and hand the leaderboard
    #duplicate rows. two decks holding the identical set of cards ARE the same
    #deck for our purposes, so the card set is the identity. the shorter name
    #wins because "Tyranid Swarm" is the deck and "Tyranid Swarm Collector's
    #Edition" is a product listing
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

    #same gate as the tag ingest: seen this exact version already, stop. an
    #empty deck_cards means a first run (or one that died halfway), do the
    #work anyway.
    #
    #DECK_FIELDS is the third condition, and it is what forces the one rerun a
    #new column needs: schema.sql adds the column empty, mtgjson's version has
    #not moved, and without this it stays empty until mtgjson happens to
    #publish. the obvious way to write that check asks the DATA instead, "is
    #any deck's source empty?", which reads right and is a trap. the day
    #mtgjson ships one Commander deck with no source field the answer is yes
    #forever, and this redownloads all 190 files every night for nothing
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

    #a card mtgjson knows about and we do not cannot be scored, and a foreign
    #key would refuse the row anyway. dropping it quietly is right: it is a
    #handful of cards (3 of 6257 measured) and they are cards our own ingest
    #chose not to keep, not gaps in mtgjson
    known = {str(r[0]) for r in conn.execute("SELECT oracle_id FROM cards")}

    with conn.cursor() as cur:
        #rebuilt from scratch every time the version moves, same philosophy as
        #line_stats and the tag tables. the cascade clears deck_cards with it
        cur.execute("TRUNCATE decks CASCADE")
        missing = 0
        card_rows = []
        for slug, d in decks.items():
            cur.execute("""INSERT INTO decks (slug, name, code, release_date, type, source)
                           VALUES (%s, %s, %s, %s, %s, %s)""",
                        (slug, d["name"], d["code"], d["date"], d["type"], d["source"]))
            for oid, count, commander in d["cards"]:
                if oid not in known:
                    missing += 1
                    continue
                card_rows.append((slug, oid, count, commander))
        #the deck rows go one at a time above because there are 166 of them and
        #each one has to land before its cards can point at it. the cards are
        #16k and they all go together, which is the difference between one
        #round trip and sixteen thousand
        cur.executemany("""INSERT INTO deck_cards (deck_slug, oracle_id, count, is_commander)
                           VALUES (%s, %s, %s, %s)""", card_rows)
        rows = len(card_rows)
        #the version marker only goes in when EVERY deck landed, because that is
        #the whole claim it makes: "this run processed mtgjson <version>". a run
        #that lost a deck did not, and recording it anyway is what turned a
        #single timeout into a permanently short board.
        #
        #the cost of leaving it out is that tomorrow redownloads all 190 files,
        #about twenty seconds of small requests next to the two gigabytes this
        #same workflow already pulls. if a deck file is broken at mtgjson's end
        #rather than in transit that repeats nightly, which is the right way
        #round: the log names the deck every time instead of the board quietly
        #being wrong
        if missed:
            print("NOT recording the version: " + str(len(missed))
                  + " deck(s) did not download, so tomorrow will try them again")
        else:
            cur.execute("""INSERT INTO meta (key, value) VALUES ('mtgjson_version', %s)
                           ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value""", (version,))
        #written in the same transaction as the rows it describes, so a run
        #that dies halfway leaves neither and the next one does the work again
        cur.execute("""INSERT INTO meta (key, value) VALUES ('mtgjson_deck_fields', %s)
                       ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value""", (DECK_FIELDS,))
    conn.commit()
    print("wrote " + str(len(decks)) + " decks and " + str(rows) + " deck cards")
    if missing:
        print("(" + str(missing) + " card slots had no matching card in our table)")
    conn.close()


if __name__ == "__main__":
    main()
