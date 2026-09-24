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


def typed_lines(text):
    #the non-blank lines as typed. split on "\n" and nothing else, because that is
    #all split_lines splits on: splitlines() also breaks at U+2028 and \x0b, and
    #the card would draw lines the limits never counted.
    #
    #a textarea posted from windows sends \r\n, and the length check counts the
    #RAW line, so without the replace a 600 character line measures 601
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    return [line for line in text.split("\n") if line.strip()]


def card_name(name):
    #the name as clean_line will read it, which swaps every occurrence of it for
    #"this card" by plain substring. 6,558 of the 60,729 stored lines say "this
    #card", so a card that names itself matches nothing without it.
    #
    #each half of a " // " name is stripped, or a stray space turns "Shivan Dragon
    #enters" into "this cardenters". a half that is blank before its first
    #comma is refused: clean_line replaces that prefix too, and replacing "" puts
    #"this card" between every character of every line
    name = (name or "").strip()
    if len(name) > MAX_NAME:
        raise Rejected("A card name is at most %d characters." % MAX_NAME)
    parts = [part.strip() for part in name.split(" // ") if part.strip()]
    if any(not part.split(",")[0].strip() for part in parts):
        raise Rejected("A card name cannot start with a comma.")
    return " // ".join(parts)


def read_custom(text, name=""):
    #typed text in, one (typed line, cleaned line) pair per non-blank line out.
    #the cleaned line is what the model reads, or None where the splitter drops
    #it, and the line picker's indexes count THESE pairs.
    #
    #the limits are checked on the raw lines BEFORE anything is cleaned: clean_line's
    #\(.*?\) is quadratic on unclosed brackets, 20,000 of them take 2s holding the
    #GIL, and gunicorn kills a worker whose heartbeat stops for 30s
    name = card_name(name)
    raw = typed_lines(text)
    if not raw:
        raise Rejected("Type the rules text of your card, one ability per line.")
    longest = max(len(line) for line in raw)
    if longest > MAX_CHARS:
        raise Rejected("One line is %d characters. The longest line on a real card is 510, "
                       "and this page takes up to %d." % (longest, MAX_CHARS))
    if len(raw) > MAX_LINES:
        raise Rejected("That is %d lines. The wordiest card in Magic has 19, and this page "
                       "takes up to %d." % (len(raw), MAX_LINES))
    #through the ingest's own splitter one line at a time, so the three character
    #floor and the cleaning are the same code that built every stored row, and
    #each typed line gets its own answer. split_lines carries nothing between lines
    pairs = []
    for line in raw:
        got = split_lines({"oracle_text": line, "name": name})
        pairs.append((line, got[0][0] if got else None))
    cleaned = [c for _, c in pairs if c]
    if not cleaned:
        raise Rejected("Nothing left to compare once reminder text and the card's own name "
                       "come out. Try a full sentence.")
    #"this card" is 9 characters, so a short name can clean a line LONGER. the
    #service refuses past its own 600, and a refusal is a 500
    longest = max(len(c) for c in cleaned)
    if longest > MAX_CHARS:
        raise Rejected("With the card's name swapped for \"this card\", one line is %d "
                       "characters, and this page takes up to %d." % (longest, MAX_CHARS))
    return pairs


def ranked_lines(pairs, kept):
    #what custom_score takes: every readable cleaned line, since the model sees
    #the whole card, and which of those the list ranks on. kept indexes into pairs
    readable = [(i, cleaned) for i, (_, cleaned) in enumerate(pairs) if cleaned]
    lines = [cleaned for _, cleaned in readable]
    rank_on = {n for n, (i, _) in enumerate(readable) if i in kept}
    return lines, rank_on


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


def line_neighbours(conn, vectors, exclude_id=None):
    #the SHARE_K stored lines nearest each typed one, with their similarity.
    #
    #NO FILTERS REACH THIS QUERY. how original a card is cannot depend on which
    #colours the visitor is browsing, and a filtered nearest neighbour would make
    #the sentence move when the list does.
    #
    #ORDER BY with a LIMIT is what walks the hnsw index. a literal
    #SELECT max(1 - (embedding <=> %s)) reads every vector in the table.
    #
    #its own function because tools/show_chips.py asks the same question of real
    #cards, and a second copy of this query is a second thing to keep in step
    mine = "AND l.oracle_id <> %s " if exclude_id is not None else ""
    around = []
    for vec in vectors:
        params = ([vec] + ([exclude_id] if exclude_id is not None else [])
                  + [vec, autotags.SHARE_K])
        around.append(conn.execute("""
            SELECT l.id, 1 - (l.""" + EMBED_COL + """ <=> %s) AS sim
            FROM lines l
            WHERE NOT l.whole AND l.""" + EMBED_COL + """ IS NOT NULL """ + mine + """
            ORDER BY l.""" + EMBED_COL + """ <=> %s
            LIMIT %s
        """, params).fetchall())
    return around


def probe_stale(conn):
    #tag_probe's 768 weights are fitted to ONE model's vector space. a model swap
    #refills lines.embedding through lines_new and empties line_tags, and touches
    #tag_probe nowhere, so the weights then score the new vectors as noise: every
    #number still lands in [0,1], the blend still runs, the chips still render and
    #mean nothing. no error and no empty state, which is why this is asked rather
    #than waited for.
    #
    #the WEIGHTS decide, not the name: a retrain released under the same repo
    #keeps it. tools/load_tag_probe.py stamps meta.tag_probe_sha256 with the
    #release the probe was trained against, the ingest records embed_sha256 for
    #the vectors, and a missing stamp counts as stale, an unprovable match being
    #the thing refused.
    #
    #names alone only while NEITHER sha is recorded: a database the ingest has
    #not run against since it began recording them. its next run records both
    #at once. returns the reason, or "" when the chips can be trusted
    said = {r["key"]: r["value"] for r in conn.execute(
        "SELECT key, value FROM meta WHERE key IN "
        "('embed_model', 'embed_sha256', 'tag_probe_model', 'tag_probe_sha256')")}
    retrain = ("retrain it on these vectors (finetune/freeze_tagdata.py, then "
               "finetune/make_tagprobe.py) and load it with tools/load_tag_probe.py")
    weights, trained = said.get("embed_sha256"), said.get("tag_probe_sha256")
    if weights or trained:
        if not trained:
            return "tag_probe carries no weights stamp: " + retrain
        if not weights:
            return "meta has no embed_sha256, so no ingest has recorded which weights made the vectors"
        if trained != weights:
            return ("tag_probe was trained against weights " + trained[:12] + " and the vectors are " +
                    weights[:12] + ": " + retrain)
        return ""
    model, stamped = said.get("embed_model"), said.get("tag_probe_model")
    if not stamped:
        return "tag_probe carries no model stamp: " + retrain
    if not model:
        return "meta has no embed_model, so this database has never been through an ingest"
    if stamped != model:
        return "tag_probe was loaded against " + stamped + " and the vectors are " + model + ": " + retrain
    return ""


def tag_chips(conn, vectors, around, type_line=""):
    #what the typed text is ABOUT, as chips under the form. the rule is
    #web/autotags.py's and the numbers behind it are tag_probe's; this is only
    #where the two halves are fetched.
    #
    #an empty tag_probe means tools/load_tag_probe.py has never run against this
    #database, and the page then shows NO chips rather than the neighbour half
    #on its own: without a probe a tag tops out at 0.30 against a 0.40 bar, so
    #what survives is whatever the top-up to two lets through, which reads like
    #a worse rule rather than a missing one.
    #
    #a probe that cannot be proved to match the vectors takes the same route out
    if probe_stale(conn):
        return []
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
    #iterating a dict is one refactor away from losing it. the score rides along
    #unshown: the page is a list and not a verdict, and a percent beside a chip
    #reads as one. tools/show_chips.py is what needs it, to tell a chip that
    #cleared the bar from one the top-up to two let through
    return [{"tag": t, "description": said.get(t, ""), "score": kept[t]} for t in kept]


def custom_score(lines, filters, sort, offset=0, band=None, currency="usd", exclude_id=None,
                 type_line="", want_chips=True, rank_on=None):
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
                              (list(lines),)):
            counts[r["line_text"]] = r["count"]

        around = line_neighbours(conn, vectors, exclude_id)
        #the FIRST of the ten is the row this used to ask for on its own, so the
        #sentence below is unchanged by the chips needing nine more
        nearest = [rows[0]["sim"] if rows else 0.0 for rows in around]

        #the MOST ISOLATED line decides, which is the rule recompute_uniqueness
        #applies to every printed card. one genuinely new ability makes a card
        #original even if everything else on it is Flying.
        #
        #over EVERY typed line, never the picked ones: rank_on below is a control
        #on the list, and this sentence is about the card. clicking a line used to
        #move it, which is a calibrated number answering a different question
        uniqueness = 1 - min(nearest) if nearest else 0.0
        below, total = rules_standing(conn, uniqueness)
        #/custom/more asks for the next page of the same list and redraws no
        #chips, so it does not pay for them
        #also over every line, for the same reason and one more: the 98% marked
        #precision was measured on whole cards, so chips from one line of one are
        #a number nobody has measured
        chips = tag_chips(conn, vectors, around, type_line) if want_chips else []

    #rank_on is the only thing the picked lines touch: which lines the LIST is
    #ranked on. indexes into lines, and None means all of them
    qlines = [{"line_text": text, "embedding": vec, "count": counts.get(text, 1)}
              for n, (text, vec) in enumerate(zip(lines, vectors))
              if rank_on is None or n in rank_on]
    #anchor empty: phase C scores the list on rules text alone. the chips and
    #the tag side of the list arrive in T7, and the sentence never moves
    results, has_more, next_band = similar_from_lines(
        qlines, ((), (), None), exclude_id, filters, TIER_CUT, sort,
        offset=offset, band=band, currency=currency)
    return {"counts": counts,
            "results": results, "has_more": has_more, "next_band": next_band,
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


def read_picked_lines(how_many):
    #which lines were CLICKED on the card, as indexes posted in hidden inputs.
    #empty is the resting state and means the whole card, the way /search's own
    #picker means it, so this is the set to draw and not the set to score.
    #
    #isascii() BEFORE isdigit(): "²".isdigit() is True and int("²") raises, so the
    #pair on its own is a 500 on a posted body
    picked = set()
    for part in request.form.getlist("lines"):
        part = part.strip()
        if part.isascii() and part.isdigit():
            picked.add(int(part))
    return picked & set(range(how_many))


def read_kept(how_many):
    #what actually gets scored. clicking nothing ranks on everything, which is
    #also the only answer to the last line being clicked off
    return read_picked_lines(how_many) or set(range(how_many))


def form_page(text, name, type_line="", pairs=(), **extra):
    #every answer this page has renders through here, so a rejection, a service
    #that did not wake and a full set of results all come back with the same
    #controls and the same text still in them.
    #
    #pairs is read_custom's, and absent on a rejection: text that failed the
    #limits is drawn as typed and never cleaned. counts arrive in extra when
    #there was a database read to get them from, and without one the card says
    #nothing about how common a line is rather than "no printed card says this"
    from app import CARD_TYPES

    picked = extra.pop("picked", None) or set()
    counts = extra.pop("counts", None)
    typed = [{"idx": i, "text": line, "cleaned": cleaned,
              "picked": i in picked,
              #absent from line_stats means NO printed card says it, which is not
              #the same as one card saying it, and the weighting reads both as 1
              "count": counts.get(cleaned) if cleaned and counts is not None else None}
             for i, (line, cleaned) in enumerate(pairs)]

    return render_template("custom.html", text=text, name=name, types=CARD_TYPES,
                           #capped where read_custom turns the form away, or a
                           #pasted megabyte draws a megabyte of card
                           preview=typed_lines(text)[:MAX_LINES], max_name=MAX_NAME,
                           max_lines=MAX_LINES,
                           typed=typed, counted=counts is not None, type_line=type_line,
                           max_type=MAX_TYPE,
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
    #the filters, sort and currency go back on EVERY page this answers, so a
    #retry after a cold wake or a fixed typo asks the same question again
    filters = read_filters()
    sort_field, sort_dir = read_sort_parts()
    controls = {"cur": filters["cur"], "sort_fields": SORT_FIELDS, "sort_field": sort_field,
                "sort_dir": sort_dir, "focus": focus_class(sort_field)}
    try:
        #the limits are checked against EVERYTHING typed, so narrowing the ranking
        #to one line cannot talk a card that is too long or too wide through
        pairs = read_custom(text, name)
    except Rejected as e:
        #the message names the limit and is written for whoever typed it, so it
        #goes on the page as it is. nothing has reached the model yet, which is
        #the whole point of checking here
        return form_page(text, name, type_line, message=str(e), **controls)

    #the model sees the whole card either way. the picks only say which of those
    #lines the list is ranked on, so the sentence and the chips do not move
    picked = read_picked_lines(len(pairs))
    lines, rank_on = ranked_lines(pairs, picked or set(range(len(pairs))))
    if not rank_on:
        #only reachable by a posted body: a line the splitter drops is not clickable
        return form_page(text, name, type_line, pairs, picked=picked,
                         message="Pick a line the matcher can read.", **controls)

    try:
        scored = custom_score(lines, filters, read_sort(), currency=filters["cur"],
                              type_line=type_line, rank_on=rank_on)
    except embedder.EmbedderDown:
        #ASLEEP or still starting, which is a minute of waiting and not a fault.
        #EmbedderRefused is deliberately not caught: it means this page and the
        #service disagree about their own limits, and a bug worded as a nap
        #would never get looked at
        return form_page(text, name, type_line, pairs, picked=picked,
                         message="The matcher didn't wake up in time. Try again in a minute.",
                         **controls), 503

    return form_page(text, name, type_line, pairs, answered=True, words=scored["words"],
                     chips=scored["chips"], picked=picked, counts=scored["counts"],
                     results=scored["results"], has_more=scored["has_more"],
                     next_band=scored["next_band"], errors=filters["errors"], **controls)


@bp.route("/custom/more", methods=["POST"])
def custom_more():
    #the shape /more returns, so the button on the results grid is the same
    #button. it POSTS because the text has to come with it and there is no card
    #name to send instead
    from app import read_filters, read_sort
    import embedder

    controls_from_form()
    text = request.form.get("text", "")
    name = request.form.get("name", "")
    try:
        pairs = read_custom(text, name)
    except Rejected:
        return {"results": [], "has_more": False, "next_band": None}
    #the picks ride along in the posted form, so page two has to score the same
    #lines page one did or the list it appends to changes underneath it
    lines, rank_on = ranked_lines(pairs, read_kept(len(pairs)))
    if not rank_on:
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
                              currency=filters["cur"], want_chips=False, rank_on=rank_on)
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
