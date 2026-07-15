#axis 2: conceptual similarity from the community tags (card_tags/tags,
#filled by ingest/tags.py). two cards are conceptually close when they share
#tags, weighted so rare tags count hard (sharing "wheel" means far more than
#sharing "removal") - the same idf idea the line engine uses, applied to tags.
#the weights (tags.idf) and each card's vector length (card_tag_norms) are
#baked at ingest so queries stay cheap. the raw score is a cosine over the
#idf-weighted tag vectors, which lives in a compressed band (real concept
#matches ~0.5-0.7, related families ~0.2-0.35), so a calibration map turns it
#into the percent the site shows. the gate is defined in displayed units on
#purpose: the map is what changes when the scorer improves, the promise
#"80 means a good match" never does

#raw cosine -> displayed percent, piecewise linear through hand-judged pairs
#(2026-07-15, scored against the ingested tagger data):
#  0.55 Shadrix/Gluntch          real concept match, must clear the gate
#  0.68 Boots/Greaves            near-substitutes
#  0.35 Shadrix/Font of Mythos   close but generic (selective vs blanket hug)
#  0.22 Bolt/Murder              same family, different everything else
#  0.10 and below                shared-tag noise
#provisional seed from 8 judged pairs - refine as axis-2 reports accumulate,
#the exam in finetune/axis2_bakeoff.py keeps it honest
CALIBRATION = [(0.0, 0), (0.10, 35), (0.22, 55), (0.35, 70), (0.55, 82), (0.68, 90), (1.0, 100)]
MIN_CONCEPT = 80


def to_display(raw):
    #walk the piecewise map. monotone, so orderings survive the translation
    raw = max(0.0, min(1.0, raw))
    for (x0, y0), (x1, y1) in zip(CALIBRATION, CALIBRATION[1:]):
        if raw <= x1:
            return round(y0 + (y1 - y0) * (raw - x0) / (x1 - x0))
    return 100


def from_display(pct):
    #the map walked backwards, so gates written in displayed units ("show
    #concept matches of 80+") can become raw cutoffs inside sql
    pct = max(0, min(100, pct))
    for (x0, y0), (x1, y1) in zip(CALIBRATION, CALIBRATION[1:]):
        if pct <= y1:
            return x0 + (x1 - x0) * (pct - y0) / (y1 - y0)
    return 1.0


def raw_sim(conn, oracle_a, oracle_b):
    #cosine between two cards' idf-weighted tag vectors, for the eval scripts
    norms = dict(conn.execute(
        "SELECT oracle_id, norm FROM card_tag_norms WHERE oracle_id IN (%s, %s)",
        (oracle_a, oracle_b)).fetchall())
    if len(norms) < 2:
        return 0.0  #one of the cards has no tags at all
    shared = conn.execute("""
        SELECT coalesce(sum(t.idf * t.idf), 0)
        FROM card_tags ca
        JOIN card_tags cb ON cb.tag = ca.tag AND cb.oracle_id = %s
        JOIN tags t ON t.tag = ca.tag
        WHERE ca.oracle_id = %s""", (oracle_b, oracle_a)).fetchone()[0]
    return shared / (norms[oracle_a] * norms[oracle_b])


def top_matches(conn, oracle_id, limit=20):
    #the site-facing query: every card sharing at least one tag with the
    #anchor, scored right in the database. the join only ever touches the
    #anchor's own tags, the norms fold the rest of each vector in
    return conn.execute("""
        WITH anchor AS (
            SELECT ct.tag, t.idf FROM card_tags ct
            JOIN tags t ON t.tag = ct.tag
            WHERE ct.oracle_id = %s
        )
        SELECT ct.oracle_id,
               sum(a.idf * a.idf) / (na.norm * nc.norm) AS raw
        FROM card_tags ct
        JOIN anchor a ON a.tag = ct.tag
        JOIN card_tag_norms nc ON nc.oracle_id = ct.oracle_id
        JOIN card_tag_norms na ON na.oracle_id = %s
        WHERE ct.oracle_id != %s
        GROUP BY ct.oracle_id, na.norm, nc.norm
        ORDER BY raw DESC
        LIMIT %s""", (oracle_id, oracle_id, oracle_id, limit)).fetchall()
