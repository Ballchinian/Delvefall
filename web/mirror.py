#the things web/ does NOT own. every name in this file is a copy of something
#whose real home is elsewhere in the repo, kept here because railway only
#deploys the web folder and the rest of the tree is not on the box.
#
#they live together in one small file so the drift guard has one place to look.
#tools/check_sync.py compares each of them against its source of truth and the
#check workflow runs it on every push, so a copy that stops matching cannot
#reach a deploy unnoticed. moving anything out of here means updating the paths
#in that script in the same commit, or the guard quietly stops guarding it.
#
#   clean_line, reminder_is_the_rule, REMINDER_KEYWORDS   common/cards.py
#   embed_column, EMBED_COLUMNS                           ingest/attribute.py
#   CALIBRATION (seed)                                    common/concept.py
#   MECH_CALIBRATION (seed)                               ingest/update.py
#   line_weight, mech_display                             finetune/exam_pairs.py
#
#nothing in here imports flask. it is arithmetic and string cleaning, which is
#what makes it safe to compare against scripts that never heard of a request

import re
import os
import math
import json

from db import pool
from prefix_words import PREFIX_WORDS

#copied from common/cards.py because railway only deploys the web folder.
#these three have to stay identical to what the ingest used, otherwise the
#line picker cant match the lines shown on the page back to their rows in the
#database. see common/cards.py for why the keyword list looks like this
REMINDER_KEYWORDS = {
    "overload", "cascade", "storm", "cycling", "flashback", "morph", "disguise",
    "madness", "convoke", "delve", "buyback", "entwine", "replicate", "embalm",
    "eternalize", "unearth", "disturb", "blitz", "bargain", "craft", "mutate",
    "foretell", "bestow", "improvise", "emerge", "evoke", "dash", "spectacle",
    "surge", "escalate", "splice", "rebound", "conspire", "retrace", "miracle",
    "ninjutsu", "prowl", "transmute", "scavenge", "encore", "outlast",
}

_BARE_KEYWORD = re.compile(r"[A-Za-z][A-Za-z'’ -]*(?:\s*\{[^}]*\})*")


def reminder_is_the_rule(stripped):
    text = stripped.strip().rstrip(".")
    if not text:
        return False
    for part in text.split(","):
        part = part.strip()
        if part and not _BARE_KEYWORD.fullmatch(part):
            return False
    first = re.split(r"[^A-Za-z'’-]", text, maxsplit=1)[0].lower()
    return first in REMINDER_KEYWORDS


def clean_line(line, card_name):
    stripped = re.sub(r"\(.*?\)", "", line)
    if reminder_is_the_rule(stripped):
        line = line.replace("(", "").replace(")", "")
    else:
        line = stripped
    #flavour prefixes go, exactly like the ingest side: table rows ("10-19 |",
    #"12+ |"), saga chapters, and scryfall's catalog of ability/flavor words
    #before a dash. see common/cards.py for why the row pattern takes a hyphen
    #and a plus as well as the em dash it was originally written with
    line = re.sub(r"^\d+(?:\s*[-–—]\s*\d+|\+)?\s*\|\s*", "", line)
    line = re.sub(r"^[IVX]+(?:, [IVX]+)*\s+—\s+", "", line)
    m = re.match(r"^([^—•|]{1,40}?)\s+—\s+(?=\S)", line)
    if m and m.group(1) in PREFIX_WORDS:
        line = line[m.end():]
    line = line.replace(card_name, "this card")
    if "," in card_name:
        line = line.replace(card_name.split(",")[0], "this card")
    return line.strip()


#lines like "Flying" appear on thousands of cards, and if we don't do anything
#about it every flying creature "matches" every other flying creature at 100%
#and the results are useless. so common lines get weighted down when ranking.
#basically a homemade version of idf from search engines.
#
#the old curve started punishing at count 2, which buried exactly the best
#results: a line shared by 2 cards means someone printed a functional reprint
#of it, and that reprint is the match people came for. so nothing gets
#punished until a line is on more than 5 cards, then it falls off gently
def line_weight(count):
    if count <= 5:
        return 1.0
    return 1.0 / (1.0 + math.log10(count / 5.0))


#which column the searches read their vectors out of. the point is that trying
#a new embedding model stops being a one way door: the new vectors go into
#embedding_v2 (see common/schema.sql), this flips the site over to them, and
#unsetting it flips straight back with the old numbers still sitting there.
#
#the value lands INSIDE sql strings, so it is checked against a fixed list
#rather than trusted. anything else and we would be one typo in a railway
#variable away from an injection point on every search.
#
#defined UP HERE, above the calibration, because load_calibration reads it to
#decide which map belongs to the column being served
EMBED_COLUMNS = ("embedding", "embedding_v2")


def embed_column():
    col = os.environ.get("EMBED_COLUMN", "").strip() or "embedding"
    if col not in EMBED_COLUMNS:
        raise ValueError("EMBED_COLUMN must be one of " + ", ".join(EMBED_COLUMNS))
    return col


EMBED_COL = embed_column()


#axis 2: how conceptually close two cards are, scored from the community
#tags the ingest bakes into card_tags/tags. the raw cosine lives in a
#compressed band, this map turns it into the percent the site shows, and
#the gate is written in displayed units on purpose.
#
#this and MECH_CALIBRATION below are SEEDS: the ingest writes the real maps
#into meta next to the model name they're anchored to, and load_calibration
#(further down, once both are defined) makes the database's word win. these
#only hold until the first ingest run against a database, and a model swap
#carries its new map along with its new vectors automatically
CALIBRATION = [(0.0, 0), (0.13, 35), (0.26, 55), (0.45, 70), (0.59, 82), (0.68, 90), (1.0, 100)]


def concept_display(raw):
    raw = max(0.0, min(1.0, raw))
    for (x0, y0), (x1, y1) in zip(CALIBRATION, CALIBRATION[1:]):
        if raw <= x1:
            return round(y0 + (y1 - y0) * (raw - x0) / (x1 - x0))
    return 100


def concept_raw_gate(pct):
    #the map walked backwards, so the displayed gate becomes a raw sql cutoff
    pct = max(0, min(100, pct))
    for (x0, y0), (x1, y1) in zip(CALIBRATION, CALIBRATION[1:]):
        if pct <= y1:
            return x0 + (x1 - x0) * (pct - y0) / (y1 - y0)
    return 1.0


#the mechanical axis wears a calibration map too, same shape as the concept
#one. raw cosine is arbitrary per model, so the displayed percent is pinned
#to judged pairs instead. the map is anchored to the tuned embeddinggemma
#the ingest embeds with, and the full story of the anchors lives next to
#EMBED_MODEL in ingest/update.py, which is the source of truth that lands
#in meta. this copy is the seed for databases the ingest hasn't touched yet
MECH_CALIBRATION = [(0.0, 0), (0.30, 30), (0.42, 45), (0.62, 65), (0.76, 80), (0.90, 92), (1.0, 100)]


def load_calibration():
    #the maps the ingest wrote into meta replace the seeds above, so the
    #percents the site shows always belong to the model that made the
    #vectors. a database the ingest has never run against has no meta rows
    #(maybe no meta table), then the seeds hold.
    #
    #a trial column needs its OWN map, or every percent on the page is a lie:
    #cosines sit in a different band per model, and the meta row belongs to
    #whichever model filled lines.embedding. so when EMBED_COLUMN points
    #somewhere else, prefer a key suffixed with it, and fall back to the
    #shared one where a trial has not been calibrated yet. measured
    #2026-07-22: without this a near verbatim match read 62% under the trial
    #model where the refit puts it at 77%
    global CALIBRATION, MECH_CALIBRATION
    suffix = "" if EMBED_COL == "embedding" else "_" + EMBED_COL
    try:
        with pool.connection() as conn:
            for key in ("concept_calibration", "mech_calibration"):
                row = None
                if suffix:
                    row = conn.execute("SELECT value FROM meta WHERE key = %s",
                                       (key + suffix,)).fetchone()
                if row is None:
                    row = conn.execute("SELECT value FROM meta WHERE key = %s", (key,)).fetchone()
                if row:
                    pts = [(float(x), float(y)) for x, y in json.loads(row["value"])]
                    if key == "concept_calibration":
                        CALIBRATION = pts
                    else:
                        MECH_CALIBRATION = pts
    except Exception:
        pass


load_calibration()


def mech_display(raw):
    raw = max(0.0, min(1.0, raw))
    for (x0, y0), (x1, y1) in zip(MECH_CALIBRATION, MECH_CALIBRATION[1:]):
        if raw <= x1:
            return round(y0 + (y1 - y0) * (raw - x0) / (x1 - x0))
    return 100
