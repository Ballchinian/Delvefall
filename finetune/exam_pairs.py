#axis 1's absolute tests: the user reports in testing_list/exam_pairs.md, each scored
#the way the site would. the report's anchor line as the picked line, the winning
#pair chosen by idf-weighted similarity (best_sim in web/app.py), and the
#calibration map the ingest wrote into meta. should-match passes at or above the
#gate, should-not below it.
#    python -m finetune.exam_pairs
#with DATABASE_URL set

import os
import re
import sys
import json
import math

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import psycopg

from common.cards import clean_line
from ingest.update import MECH_CALIBRATION as SEED_CALIBRATION

#where a PURE mechanical score's strong tier ends, in display units. web/app.py's
#TIER_CUT is 70 because its badge averages the two axes and averages rarely reach
#80; one axis alone sits at 80, which is the model's real quality boundary
GATE = 80

PAIRS_MD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "testing_list", "exam_pairs.md")

#resolved in main the way load_calibration in web/mirror.py does it: the meta row
#the ingest wrote wins, the seed holding for a database it has not touched yet
MECH_CALIBRATION = None

#copies from web/mirror.py (web/ can't be imported, railway deploys it alone).
#tools/check_sync.py keeps them identical


def line_weight(count):
    if count <= 5:
        return 1.0
    return 1.0 / (1.0 + math.log10(count / 5.0))


def mech_display(raw):
    raw = max(0.0, min(1.0, raw))
    for (x0, y0), (x1, y1) in zip(MECH_CALIBRATION, MECH_CALIBRATION[1:]):
        if raw <= x1:
            return round(y0 + (y1 - y0) * (raw - x0) / (x1 - x0))
    return 100


def parse_reports(path):
    #entries are "**Anchor:** Card - `line`" followed by a "**Match:**" or
    #"**NOT:**" line naming the other card. the notes are for humans
    entries = []
    section = None
    anchor = None
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.startswith("# Should-match"):
                section, anchor = "should-match", None
            elif line.startswith("# Should-NOT"):
                section, anchor = "should-NOT", None
            m = re.match(r"\s*\*\*Anchor:\*\* (.+?) - `(.*)`\s*$", line)
            if m:
                anchor = (m.group(1), m.group(2))
                continue
            m = re.match(r"\s*\*\*(?:Match|NOT):\*\* (.+?) - `", line)
            if m and anchor and section:
                entries.append((section, anchor[0], anchor[1], m.group(1)))
    return entries


def find_card(conn, name):
    #reports name the face the user saw, the cards table stores full names
    #("A // B"), so a bare face name resolves through the split patterns
    row = conn.execute("SELECT oracle_id, name FROM cards WHERE name = %s", (name,)).fetchone()
    if not row:
        row = conn.execute("SELECT oracle_id, name FROM cards WHERE name LIKE %s OR name LIKE %s",
                           (name + " // %", "% // " + name)).fetchone()
    if not row:
        sys.exit("card not in database: " + name)
    return row


def score_pair(conn, anchor_id, anchor_db_name, anchor_line, other_id):
    #best_sim from web/app.py with the anchor line pinned: the winning pair is
    #chosen by WEIGHTED similarity, the number returned is that pair's real one.
    #cleaned with the database's card name, as the ingest did when it made the row
    sql = """
        SELECT 1 - (a.embedding <=> b.embedding) AS sim,
               coalesce(s.count, 1) AS count,
               b.line_text
        FROM lines a
        JOIN lines b ON b.oracle_id = %s AND NOT b.whole
        LEFT JOIN line_stats s ON s.line_text = a.line_text
        WHERE a.oracle_id = %s AND NOT a.whole
    """
    picked = clean_line(anchor_line, anchor_db_name)
    rows = conn.execute(sql + " AND a.line_text = %s", (other_id, anchor_id, picked)).fetchall()
    pinned = True
    if not rows:
        #the pasted line no longer cleans to a database row (retemplated text, or
        #clean_line moved on), so score every anchor line instead
        pinned = False
        rows = conn.execute(sql, (other_id, anchor_id)).fetchall()
    best = None
    for sim, count, their_line in rows:
        weighted = line_weight(count) * sim
        if best is None or weighted > best[0]:
            best = (weighted, sim, their_line)
    if best is None:
        return None, None, pinned
    return best[1], best[2], pinned


def main():
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("set DATABASE_URL first (the postgres connection string)")
        sys.exit(1)
    conn = psycopg.connect(db_url)

    global MECH_CALIBRATION
    row = conn.execute("SELECT value FROM meta WHERE key = 'mech_calibration'").fetchone()
    if row:
        MECH_CALIBRATION = [(float(x), float(y)) for x, y in json.loads(row[0])]
    else:
        MECH_CALIBRATION = SEED_CALIBRATION
        print("(no mech_calibration in meta, judging on the seed map like the site does)")

    entries = parse_reports(PAIRS_MD)
    if not entries:
        sys.exit("no reports parsed out of " + PAIRS_MD)

    score = 0
    section_shown = None
    for section, a_name, a_line, o_name in entries:
        if section != section_shown:
            side = ">=" if section == "should-match" else "<"
            print(section + " (pass: displayed " + side + " " + str(GATE) + ")")
            section_shown = section
        a_id, a_db = find_card(conn, a_name)
        o_id, _ = find_card(conn, o_name)
        raw, their_line, pinned = score_pair(conn, a_id, a_db, a_line, o_id)
        if raw is None:
            print("  ???? %s vs %s: no scorable lines" % (a_name, o_name))
            continue
        shown = mech_display(raw)
        ok = shown >= GATE if section == "should-match" else shown < GATE
        score += ok
        note = "" if pinned else "  (anchor line not in db, scored all its lines)"
        print("  %s %s vs %s: raw %.3f -> %d%%  via \"%s\"%s"
              % ("PASS" if ok else "FAIL", a_name, o_name, raw, shown, their_line[:60], note))

    conn.close()
    print(str(score) + "/" + str(len(entries)))


if __name__ == "__main__":
    main()
