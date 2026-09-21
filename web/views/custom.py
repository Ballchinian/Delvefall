#---- /custom: the printed cards that already do something like a card you invented

#a LIST, never a verdict. the page never says "this already exists": a verdict
#that misfires makes the site look broken, where a list of evidence cannot.
#
#the originality sentence is counted on RULES TEXT ALONE and stays that way.
#/unique ranks printed cards on rules text blended with the concept axis, so the
#same card typed in here reads a different percent from its own /unique page.
#that is why the wording differs ("Its rules text is more original than...") and
#why the page says the chips do not count toward it. phase T measured inferring
#the concept side from typed text and it does not survive: rank correlation 0.43
#against the stored value, because a card's tag-side originality comes from its
#rare one-off tags and inference only ever finds tags nearby cards already carry.
#
#app.py is imported INSIDE the functions, not at the top: it registers this
#blueprint at the bottom of its own module, so a module-level import closes the
#circle. views/meta.py does the same for the same reason.

from flask import Blueprint

from db import pool
from mirror import EMBED_COL, line_weight, split_lines

bp = Blueprint("custom", __name__)

#the most lines on a stored card is 19 and the longest stored line is 510
#characters (measured 2026-09-21), so both of these clear the real data with
#room. they are floors a new set can walk into, which is why the message says
#the number rather than "too long"
MAX_LINES = 20
MAX_CHARS = 600
MAX_NAME = 150


class Rejected(Exception):
    #the text cannot be scored, and the reason is something the visitor can fix.
    #raised BEFORE any call to the model, so a card nobody could score never
    #wakes the service
    pass


def read_custom(text, name=""):
    #typed text in, the cleaned lines the model will see out.
    #
    #the name matters more than it looks: clean_line swaps it for "this card",
    #which is how the stored lines are written, and 6,558 of the 60,729 stored
    #lines carry that phrase. without it a card that names itself matches
    #nothing, because no printed card says "Shivan Dragon" either
    name = (name or "").strip()
    if len(name) > MAX_NAME:
        raise Rejected("A card name is at most %d characters." % MAX_NAME)
    #a textarea posted from windows sends \r\n. clean_line's closing strip()
    #takes the \r off the text itself, but the length check below counts the RAW
    #line, so without this a 600 character line measures 601 and is turned away
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    raw = [line for line in text.split("\n") if line.strip()]
    if not raw:
        raise Rejected("Type the rules text of your card, one ability per line.")
    longest = max(len(line) for line in raw)
    if longest > MAX_CHARS:
        raise Rejected("One line is %d characters. The longest line on a real card is 510, "
                       "and this page takes up to %d." % (longest, MAX_CHARS))
    if len(raw) > MAX_LINES:
        raise Rejected("That is %d lines. The wordiest card in Magic has 19, and this page "
                       "takes up to %d." % (len(raw), MAX_LINES))
    #through the ingest's own splitter, on a card shaped like the ones it reads,
    #so the three character floor and the cleaning are the same code that built
    #every row this will be compared against
    lines = [line for line, face in split_lines({"oracle_text": text, "name": name})]
    if not lines:
        raise Rejected("Nothing left to compare once reminder text and the card's own name "
                       "come out. Try a full sentence.")
    return lines


def custom_words(below, total):
    #ALWAYS a percentage, and floored the way unique_words floors it.
    #
    #the three things it must never say, all of which /unique does say about
    #printed cards: "other cards already do everything it does", "#N most
    #unique card in Magic", and "the most unique card in Magic". a typed card is
    #not in Magic, so a rank among Magic cards is a claim about a population it
    #is not a member of
    if not total:
        return "Its rules text is more original than 0.0% of Magic cards"
    return "Its rules text is more original than %.1f%% of Magic cards" % (1000 * below // total / 10)


def rules_standing(conn, uniqueness):
    #(below, total) over cards.uniqueness ALONE, against the commander legal
    #pool /unique counts in by default whatever filters the page is wearing.
    #
    #this is unique_standing with the concept axis taken out, and the difference
    #is deliberate: /unique blends the two, so a printed card typed into this
    #page reads a different percent from its own /unique page. the wording says
    #"its rules text" for exactly that reason.
    #
    #UNIQUE_NOISE ties the bottom. scores are float4, so a card whose every line
    #is printed elsewhere lands a step either side of zero, and without the floor
    #thousands of cards that all "already exist" would sort against each other on
    #rounding error. 7,253 of 31,295 sit in that tie
    from app import UNIQUE_NOISE

    x = uniqueness if uniqueness >= UNIQUE_NOISE else 0.0
    row = conn.execute("""
        SELECT count(*) FILTER (WHERE b < %(x)s) AS below, count(*) AS total
        FROM (SELECT CASE WHEN c.uniqueness < %(noise)s THEN 0 ELSE c.uniqueness END AS b
              FROM cards c
              WHERE c.uniqueness IS NOT NULL AND c.legal_commander) t
    """, {"x": x, "noise": UNIQUE_NOISE}).fetchone()
    return row["below"], row["total"]


def custom_score(lines, filters, sort, offset=0, band=None, currency="usd", exclude_id=None):
    #the whole of the results route below the form, so the tests and
    #tools/check_custom.py can call it without going through http.
    #
    #exclude_id is for those two only: check_custom scores a printed card's own
    #text with that card taken out and compares the answer against the stored
    #cards.uniqueness. no route passes it, because a typed card is not in the
    #table to exclude
    from app import TIER_CUT, similar_from_lines
    import embedder

    vectors = embedder.embed(lines)

    with pool.connection() as conn:
        #the idf weight of each typed line, by exact text, as find_similar reads
        #it. a line nobody has printed is absent and weighs 1, which is right:
        #the weighting only ever punishes a line for being common
        counts = {}
        for r in conn.execute("SELECT line_text, count FROM line_stats WHERE line_text = ANY(%s)",
                              (lines,)):
            counts[r["line_text"]] = r["count"]

        #NO FILTERS REACH THIS QUERY. how original a card is cannot depend on
        #which colours the visitor is browsing, and a filtered nearest neighbour
        #would make the sentence move when the list does.
        #
        #ORDER BY with a LIMIT is what walks the hnsw index. a literal
        #SELECT max(1 - (embedding <=> %s)) reads every vector in the table
        mine = "AND l.oracle_id <> %s " if exclude_id is not None else ""
        nearest = []
        for vec in vectors:
            params = [vec] + ([exclude_id] if exclude_id is not None else []) + [vec]
            row = conn.execute("""
                SELECT 1 - (l.""" + EMBED_COL + """ <=> %s) AS sim
                FROM lines l
                WHERE NOT l.whole AND l.""" + EMBED_COL + """ IS NOT NULL """ + mine + """
                ORDER BY l.""" + EMBED_COL + """ <=> %s
                LIMIT 1
            """, params).fetchone()
            nearest.append(row["sim"] if row else 0.0)

        #the MOST ISOLATED line decides, which is the rule recompute_uniqueness
        #applies to every printed card. one genuinely new ability makes a card
        #original even if everything else on it is Flying
        uniqueness = 1 - min(nearest) if nearest else 0.0
        below, total = rules_standing(conn, uniqueness)

    qlines = [{"line_text": text, "embedding": vec, "count": counts.get(text, 1)}
              for text, vec in zip(lines, vectors)]
    #anchor empty: phase C scores the list on rules text alone. the chips and
    #the tag side of the list arrive in T7, and the sentence never moves
    results, has_more, next_band = similar_from_lines(
        qlines, ((), (), None), exclude_id, filters, TIER_CUT, sort,
        offset=offset, band=band, currency=currency)
    return {"results": results, "has_more": has_more, "next_band": next_band,
            "uniqueness": uniqueness, "words": custom_words(below, total),
            "below": below, "total": total,
            #what find_similar hands the page for a printed card, so the line
            #weights and the percents mean the same thing on both
            "weights": [line_weight(counts.get(t, 1)) for t in lines]}
