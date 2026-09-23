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

from flask import Blueprint, render_template, request

import autotags
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
#the longest type line a printed card carries is 71 characters, both faces
#and the dash between them included. only the first card-type word is ever
#read, so this is a cap on what gets stored in a form field, not a rule
MAX_TYPE = 120


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


def tag_chips(conn, vectors, around, type_line=""):
    #what the typed text is ABOUT, as chips under the form. the rule is
    #web/autotags.py's and the numbers behind it are tag_probe's; this is only
    #where the two halves are fetched.
    #
    #an empty tag_probe means tools/load_tag_probe.py has never run against this
    #database, and the page then shows NO chips rather than the neighbour half
    #on its own: without a probe a tag tops out at 0.30 against a 0.40 bar, so
    #what survives is whatever the top-up to two lets through, which reads like
    #a worse rule rather than a missing one
    probe = []
    for vec in vectors:
        #(w <#> v) is the NEGATIVE inner product, hence the sign. clamped
        #because exp() overflows past 709 and a numeric error here would be a
        #500 on a page that was only asked a question
        rows = conn.execute("""
            SELECT tag, 1 / (1 + exp(-greatest(least((w <#> %s) * -1 + b, 30), -30))) AS p
            FROM tag_probe
            WHERE w IS NOT NULL
            ORDER BY p DESC
            LIMIT %s
        """, (vec, autotags.PROBE_KEEP)).fetchall()
        probe.append({r["tag"]: r["p"] for r in rows})
    if not any(probe):
        return []

    #the neighbours' tags in one query rather than one per line: the ten nearest
    #of twenty lines is still only two hundred ids
    ids = [r["id"] for rows in around for r in rows]
    carried = {}
    for r in conn.execute("SELECT line_id, tag FROM line_tags WHERE line_id = ANY(%s)", (ids,)):
        carried.setdefault(r["line_id"], []).append(r["tag"])
    share = [[(r["sim"], carried.get(r["id"], ())) for r in rows] for rows in around]

    scores = autotags.blend(autotags.probe_scores(probe), autotags.share_scores(share))
    #the description is what the chip says on hover, the way the picker on a
    #card page does it. LEFT JOIN because `tags` is rebuilt from scryfall every
    #morning and this table is not, so a tag can outlive its description
    banned, types, said = set(), {}, {}
    for r in conn.execute("""
        SELECT p.tag, p.banned, p.types, COALESCE(t.description, '') AS description
        FROM tag_probe p LEFT JOIN tags t ON t.tag = p.tag
        WHERE p.tag = ANY(%s)
    """, (list(scores),)):
        if r["banned"]:
            banned.add(r["tag"])
        types[r["tag"]] = r["types"]
        said[r["tag"]] = r["description"]
    #"other" is what card_type says when it recognised nothing, which is not a
    #type line to filter on. only a word it knows narrows anything
    kind = autotags.card_type(type_line)
    kept = autotags.chips(scores, banned=banned, type_shares=types,
                          kind=kind if kind != "other" else None)
    #a list and not the dict, because the ORDER is the ranking and a template
    #iterating a dict is one refactor away from losing it
    return [{"tag": t, "description": said.get(t, "")} for t in kept]


def custom_score(lines, filters, sort, offset=0, band=None, currency="usd", exclude_id=None,
                 type_line="", want_chips=True):
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
        nearest, around = [], []
        for vec in vectors:
            params = ([vec] + ([exclude_id] if exclude_id is not None else [])
                      + [vec, autotags.SHARE_K])
            rows = conn.execute("""
                SELECT l.id, 1 - (l.""" + EMBED_COL + """ <=> %s) AS sim
                FROM lines l
                WHERE NOT l.whole AND l.""" + EMBED_COL + """ IS NOT NULL """ + mine + """
                ORDER BY l.""" + EMBED_COL + """ <=> %s
                LIMIT %s
            """, params).fetchall()
            #ten now rather than one, because the chips need the neighbours
            #that vote. the FIRST of them is the same row this asked for
            #before, so the sentence below is unchanged
            nearest.append(rows[0]["sim"] if rows else 0.0)
            around.append(rows)

        #the MOST ISOLATED line decides, which is the rule recompute_uniqueness
        #applies to every printed card. one genuinely new ability makes a card
        #original even if everything else on it is Flying
        uniqueness = 1 - min(nearest) if nearest else 0.0
        below, total = rules_standing(conn, uniqueness)
        #/custom/more asks for the next page of the same list and redraws no
        #chips, so it does not pay for them
        chips = tag_chips(conn, vectors, around, type_line) if want_chips else []

    qlines = [{"line_text": text, "embedding": vec, "count": counts.get(text, 1)}
              for text, vec in zip(lines, vectors)]
    #anchor empty: phase C scores the list on rules text alone. the chips and
    #the tag side of the list arrive in T7, and the sentence never moves
    results, has_more, next_band = similar_from_lines(
        qlines, ((), (), None), exclude_id, filters, TIER_CUT, sort,
        offset=offset, band=band, currency=currency)
    return {"results": results, "has_more": has_more, "next_band": next_band,
            "uniqueness": uniqueness, "words": custom_words(below, total),
            "below": below, "total": total, "chips": chips,
            #what find_similar hands the page for a printed card, so the line
            #weights and the percents mean the same thing on both
            "weights": [line_weight(counts.get(t, 1)) for t in lines]}


#---- the routes ----
#
#flask names a blueprint's endpoints "custom.<function>", so these are
#custom.custom, custom.custom_post and so on, and those are the names
#visitors.py has to carry: a name matching no route counts nothing and says
#nothing about it either.


def controls_from_form():
    #read_filters(), read_sort() and partials/filters.html all read
    #request.args, and every control on this page arrives in the POST BODY
    #instead. it has to: the text runs to 12,000 characters, and a url is the
    #one place it would get written down, in an access log, by the page that
    #promises to keep none of it.
    #
    #so the body stands in as the query string for the length of the request.
    #werkzeug's cached_property has a __set__ and the request object dies with
    #the response, so nothing set here reaches another one
    request.args = request.form


def typed_lines(text):
    #the RAW lines, for the blank card. it draws what was typed, where the model
    #reads what clean_line makes of it. capped where read_custom turns the form
    #away anyway, or a pasted megabyte draws a megabyte of card
    return [line for line in (text or "").splitlines() if line.strip()][:MAX_LINES]


def form_page(text, name, type_line="", **extra):
    #every answer this page has renders through here, so a rejection, a service
    #that did not wake and a full set of results all come back with the same
    #controls and the same text still in them
    from app import CARD_TYPES

    return render_template("custom.html", text=text, name=name, types=CARD_TYPES,
                           preview=typed_lines(text), max_name=MAX_NAME, max_lines=MAX_LINES,
                           type_line=type_line, max_type=MAX_TYPE,
                           #a POST result has no url to index and must not grow
                           #one. the form itself is a page and stays open
                           noindex=request.method == "POST", **extra)


@bp.route("/custom")
def custom():
    #the empty form, and the request that counts the visitor: signal_for() calls
    #only a GET "html", so the POST below adds the act flag and nothing else,
    #even though it answers with a whole page
    return form_page("", "")


@bp.route("/custom", methods=["POST"])
def custom_post():
    from app import SORT_FIELDS, focus_class, read_filters, read_sort, read_sort_parts
    import embedder

    controls_from_form()
    name = request.form.get("name", "")
    text = request.form.get("text", "")
    #cut rather than refused: the box has a maxlength, so a longer one is a
    #posted body rather than something anybody typed, and only the first card
    #type word is read out of it anyway
    type_line = request.form.get("type_line", "")[:MAX_TYPE]
    try:
        lines = read_custom(text, name)
    except Rejected as e:
        #the message names the limit and is written for whoever typed it, so it
        #goes on the page as it is. nothing has reached the model yet, which is
        #the whole point of checking here
        return form_page(text, name, type_line, message=str(e))

    filters = read_filters()
    sort_field, sort_dir = read_sort_parts()
    try:
        scored = custom_score(lines, filters, read_sort(), currency=filters["cur"],
                              type_line=type_line)
    except embedder.EmbedderDown:
        #ASLEEP or still starting, which is a minute of waiting and not a fault.
        #EmbedderRefused is deliberately not caught: it means this page and the
        #service disagree about their own limits, and a bug worded as a nap
        #would never get looked at
        return form_page(text, name, type_line,
                         message="The matcher didn't wake up in time. Try again in a minute."), 503

    return form_page(text, name, type_line, answered=True, words=scored["words"],
                     chips=scored["chips"],
                     results=scored["results"], has_more=scored["has_more"],
                     next_band=scored["next_band"], errors=filters["errors"],
                     cur=filters["cur"], sort_fields=SORT_FIELDS, sort_field=sort_field,
                     sort_dir=sort_dir, focus=focus_class(sort_field))


@bp.route("/custom/more", methods=["POST"])
def custom_more():
    #the shape /more returns, so the button on the results grid is the same
    #button. it POSTS because the text has to come with it and there is no card
    #name to send instead
    from app import read_filters, read_sort
    import embedder

    controls_from_form()
    try:
        lines = read_custom(request.form.get("text", ""), request.form.get("name", ""))
    except Rejected:
        return {"results": [], "has_more": False, "next_band": None}
    #fail-soft like every other url reader, a doctored offset shouldn't 500
    try:
        offset = max(0, int(request.form.get("offset", 0)))
    except ValueError:
        offset = 0
    #which band of weaker matches to page through, absent for the strong tier
    try:
        band = int(request.form["band"])
    except (KeyError, ValueError):
        band = None
    filters = read_filters()
    try:
        scored = custom_score(lines, filters, read_sort(), offset=offset, band=band,
                              currency=filters["cur"], want_chips=False)
    except embedder.EmbedderDown:
        #the button says so and stays where it is. the page above it is already
        #drawn, so there is nothing to render again
        return {"results": [], "has_more": False, "next_band": None}, 503
    return {"results": scored["results"], "has_more": scored["has_more"],
            "next_band": scored["next_band"]}


@bp.route("/custom/wake", methods=["POST"])
def custom_wake():
    #fired at the first focus on the textarea. the PACKET is the point and not
    #the answer: it is what starts a sleeping container, so the model is loading
    #while somebody is still typing. 204 however it went, since the page has
    #nothing to do with what it hears back
    import embedder

    embedder.wake()
    return "", 204
