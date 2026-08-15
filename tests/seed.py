#a small deterministic world for the tests that need real rows.
#
#every name is INVENTED, so a failure never reads as a claim about an actual card
#and nobody greps the pool looking for one. the ids are fixed uuids for the same
#reason the fixture is seeded rather than sampled.
#
#the embeddings are the interesting part: a line's vector points along ONE axis,
#so two lines on the same axis sit at cosine 1 and two on different axes at 0.
#not what real embeddings look like, and exactly what a test wants, since the
#similarity between any two lines is a fact the fixture decides rather than a
#number the model happened to produce

DIMS = 768

#the anchor and its neighbourhood, all sharing a tag family so the concept axis
#has something to say about them
ANCHOR = "00000000-0000-4000-8000-000000000001"
TWIN = "00000000-0000-4000-8000-000000000002"
COUSIN = "00000000-0000-4000-8000-000000000003"
STRANGER = "00000000-0000-4000-8000-000000000004"
#tags but NO lines, so only the concept injection can find it. that is the shape
#a concept-only result has, and the branch it reaches in find_similar
#(ranked.append with no pairs) is the one a card outside the 400 row scan reaches
CONCEPT_ONLY = "00000000-0000-4000-8000-000000000005"

#three digits of counter, because DECK_FILLER runs past 99 and a uuid is
#exactly 36 characters: one digit too many and postgres rejects the literal
DECK_PREFIX = "00000000-0000-4000-8000-000001000"


def vec(axis, dims=DIMS):
    v = [0.0] * dims
    v[axis] = 1.0
    return v


#(oracle_id, name, salt, rank, cmc, price, released, type_line, text)
CARDS = [
    (ANCHOR, "Fixture Anchor", 1.00, 100, 3, "5.00", "2015-01-01",
     "Legendary Creature — Test",
     "Flying\nWhenever this card attacks, draw a card.\nSacrifice a creature: draw a card."),
    (TWIN, "Fixture Twin", 2.50, 200, 3, "6.00", "2016-01-01",
     "Creature — Test", "Whenever this card attacks, draw a card."),
    (COUSIN, "Fixture Cousin", 0.10, 300, 3, "1.00", "2017-01-01",
     "Creature — Test", "Whenever this card attacks, draw a card."),
    (STRANGER, "Fixture Stranger", 0.50, 400, 3, "2.00", "2018-01-01",
     "Creature — Test", "Destroy target land."),
    (CONCEPT_ONLY, "Fixture Ghost", 2.00, 500, 3, "3.00", "2019-01-01",
     "Creature — Test", "Whenever this card attacks, draw a card."),
]

#axis 1 is "attack trigger draws", axis 2 is "land destruction". the anchor's
#keyword line gets its own axis so nothing else answers it.
#
#its THIRD line owns a tag the twin owns too, which is what makes picking a line
#observable: narrowing to the attack line drops sac-outlet out of the anchor's
#vector and the twin's score has to move. without a second concept on the card,
#picking a line and picking nothing produce the same vector
LINES = [
    (ANCHOR, "Flying", 0),
    (ANCHOR, "Whenever this card attacks, draw a card.", 1),
    (ANCHOR, "Sacrifice a creature: draw a card.", 3),
    (TWIN, "Whenever this card attacks, draw a card.", 1),
    (COUSIN, "Whenever this card attacks, draw a card.", 1),
    (STRANGER, "Destroy target land.", 2),
]

#"Flying" is on thousands of real cards and the line weighting has to notice
LINE_COUNTS = {"Flying": 3000, "Whenever this card attacks, draw a card.": 3,
               "Destroy target land.": 4, "Sacrifice a creature: draw a card.": 5}

#which line each of the anchor's tags belongs to. "Flying" is deliberately
#ABSENT: a keyword line owns no concepts, which is why picking one has to drop
#the concept axis rather than score against a vector of nothing
LINE_TAGS = {
    (ANCHOR, "Whenever this card attacks, draw a card."): ["draw-on-attack"],
    (ANCHOR, "Sacrifice a creature: draw a card."): ["sac-outlet"],
    (TWIN, "Whenever this card attacks, draw a card."): ["draw-on-attack"],
    (COUSIN, "Whenever this card attacks, draw a card."): ["draw-on-attack"],
}

#a two level family so the anchor vector has a parent to climb to
TAGS = [
    ("draw-on-attack", ["card-advantage"], 4, 2.0, "draws when it attacks"),
    ("card-advantage", [], 4, 1.5, "gets you cards"),
    ("sac-outlet", [], 2, 2.5, "sacrifices creatures"),
    ("land-destruction", [], 1, 3.0, "kills lands"),
]

#(oracle_id, tag, inherited). the anchor, its twin, its cousin and the ghost
#all share the family; the stranger sits outside it
CARD_TAGS = [
    (ANCHOR, "draw-on-attack", False), (ANCHOR, "card-advantage", True),
    (ANCHOR, "sac-outlet", False),
    (TWIN, "draw-on-attack", False), (TWIN, "card-advantage", True),
    (TWIN, "sac-outlet", False),
    (COUSIN, "draw-on-attack", False), (COUSIN, "card-advantage", True),
    (CONCEPT_ONLY, "draw-on-attack", False), (CONCEPT_ONLY, "card-advantage", True),
    (STRANGER, "land-destruction", False),
]

INHERITED_WEIGHT = 0.5

#how many filler cards the deck panels get. metric_cards reads a deck from BOTH
#ends and caps each at DECK_EVIDENCE_MAX (48), so a deck has to clear 96 rows
#before the two slices stop overlapping and the bottom end means anything
DECK_FILLER = 120


def deck_id(i):
    return DECK_PREFIX + "%03d" % i


def build(conn):
    wipe(conn)
    for oid, name, salt, rank, cmc, price, released, type_line, text in CARDS:
        conn.execute("""
            INSERT INTO cards (oracle_id, name, mana_cost, type_line, oracle_text, image,
                               scryfall_uri, text_hash, color_identity, price_usd, price_eur,
                               cmc, game_changer, legal_commander, layout, image_back,
                               edhrec_rank, released_at, salt, uniqueness)
            VALUES (%s, %s, '{1}{U}', %s, %s, '', '', %s, 'U', %s, %s, %s, false, true,
                    'normal', '', %s, %s, %s, 0.5)
        """, (oid, name, type_line, text, name, price, price, cmc, rank, released, salt))

    for oid, text, axis in LINES:
        row = conn.execute("""
            INSERT INTO lines (oracle_id, line_text, embedding, face, whole, nn_sim)
            VALUES (%s, %s, %s, 0, false, 0.5) RETURNING id
        """, (oid, text, vec(axis))).fetchone()
        #both facts have to be on record: an empty answer and a database the
        #attribution never ran against are the same empty result set and want
        #OPPOSITE handling, so the fixture has to tell them apart as the site does
        line_id = row["id"] if hasattr(row, "keys") else row[0]
        for tag in LINE_TAGS.get((oid, text), []):
            conn.execute("""
                INSERT INTO line_tags (line_id, tag, lift, card_level) VALUES (%s, %s, 1.0, false)
            """, (line_id, tag))

    for text, count in LINE_COUNTS.items():
        conn.execute("INSERT INTO line_stats (line_text, count) VALUES (%s, %s)", (text, count))

    for tag, parents, count, idf, desc in TAGS:
        conn.execute("""
            INSERT INTO tags (tag, parents, card_count, idf, description)
            VALUES (%s, %s, %s, %s, %s)
        """, (tag, parents, count, idf, desc))

    idf = {t[0]: t[3] for t in TAGS}
    weights = {}
    for oid, tag, inherited in CARD_TAGS:
        w = idf[tag] * (INHERITED_WEIGHT if inherited else 1.0)
        conn.execute("""
            INSERT INTO card_tags (oracle_id, tag, inherited, weight) VALUES (%s, %s, %s, %s)
        """, (oid, tag, inherited, w))
        weights.setdefault(oid, []).append(w)
    for oid, ws in weights.items():
        norm = sum(w * w for w in ws) ** 0.5
        conn.execute("INSERT INTO card_tag_norms (oracle_id, norm) VALUES (%s, %s)", (oid, norm))

    #the same two tables ingest/tags.py fills, built the same way, because the
    #concept axis reads card_tag_vecs and a fixture without them would score
    #every pair at zero while every test still passed its assertions about
    #rules text. the width is read off the column so this cannot drift from
    #common/schema.sql
    width = conn.execute("""
        SELECT atttypmod FROM pg_attribute
        WHERE attrelid = 'card_tag_vecs'::regclass AND attname = 'vec'
    """).fetchone()[0]
    conn.execute("""
        INSERT INTO tag_dims (tag, dim)
        SELECT t.tag, (SELECT coalesce(max(dim), 0) FROM tag_dims)
                      + row_number() OVER (ORDER BY t.tag)
        FROM tags t WHERE NOT EXISTS (SELECT 1 FROM tag_dims d WHERE d.tag = t.tag)
    """)
    conn.execute("""
        INSERT INTO card_tag_vecs (oracle_id, vec)
        SELECT ct.oracle_id,
               ('{' || string_agg(d.dim || ':' || ct.weight::float8, ',' ORDER BY d.dim)
                    || '}/' || %s)::sparsevec
        FROM card_tags ct JOIN tag_dims d ON d.tag = ct.tag
        WHERE ct.oracle_id::text LIKE '00000000-0000-4000-8000-%%'
        GROUP BY ct.oracle_id
    """, (width,))

    #the filler deck. salt descends with the index so the true mildest card is
    #the last one, which is the thing the both-ends slice has to reach
    for i in range(DECK_FILLER):
        conn.execute("""
            INSERT INTO cards (oracle_id, name, mana_cost, type_line, oracle_text, image,
                               scryfall_uri, text_hash, color_identity, price_usd, price_eur,
                               cmc, game_changer, legal_commander, layout, image_back,
                               edhrec_rank, released_at, salt, uniqueness)
            VALUES (%s, %s, '{1}', 'Creature — Filler', 'Filler text.', '', '', %s, 'U',
                    %s, %s, 2, false, true, 'normal', '', %s, %s, %s, 0.4)
        """, (deck_id(i), "Fixture Filler %03d" % i, "filler%d" % i,
              "%.2f" % (1 + i), "%.2f" % (1 + i), 1000 + i,
              "2020-01-01", round(3.0 - i * 0.02, 4)))


def wipe(conn):
    conn.execute("DELETE FROM card_tag_vecs WHERE oracle_id::text LIKE '00000000-0000-4000-8000-%'")
    conn.execute("DELETE FROM card_tag_norms WHERE oracle_id::text LIKE '00000000-0000-4000-8000-%'")
    conn.execute("DELETE FROM card_tags WHERE oracle_id::text LIKE '00000000-0000-4000-8000-%'")
    conn.execute("DELETE FROM lines WHERE oracle_id::text LIKE '00000000-0000-4000-8000-%'")
    conn.execute("DELETE FROM cards WHERE oracle_id::text LIKE '00000000-0000-4000-8000-%'")
    conn.execute("DELETE FROM tags WHERE tag = ANY(%s)", ([t[0] for t in TAGS],))
    conn.execute("DELETE FROM line_stats WHERE line_text = ANY(%s)", (list(LINE_COUNTS),))


teardown = wipe
