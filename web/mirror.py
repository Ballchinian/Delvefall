#the things web/ does NOT own: every name here is a COPY of something whose real
#home is elsewhere, kept because railway only deploys the web folder.
#
#one file so the drift guard has one place to look. tools/check_sync.py compares
#each against its source and the check workflow runs it on every push, so moving
#anything out of here means updating that script IN THE SAME COMMIT or the guard
#quietly stops guarding it.
#
#   clean_line, reminder_is_the_rule, REMINDER_KEYWORDS   common/cards.py
#   embed_column, EMBED_COLUMNS                           ingest/attribute.py
#   CALIBRATION (seed)                                    common/concept.py
#   MECH_CALIBRATION (seed)                               ingest/update.py
#   line_weight, mech_display                             finetune/exam_pairs.py
#
#nothing here imports flask, which is what makes it comparable against scripts
#that never heard of a request

import re
import os
import math
import json

from db import pool
from prefix_words import PREFIX_WORDS

#these three have to stay IDENTICAL to what the ingest used, or the line picker
#cannot match the lines on the page back to their rows. see common/cards.py
REMINDER_KEYWORDS = {
    "overload", "cascade", "storm", "cycling", "flashback", "morph", "disguise",
    "madness", "convoke", "delve", "buyback", "entwine", "replicate", "embalm",
    "eternalize", "unearth", "disturb", "blitz", "bargain", "craft", "mutate",
    "foretell", "bestow", "improvise", "emerge", "evoke", "dash", "spectacle",
    "surge", "escalate", "splice", "rebound", "conspire", "retrace", "miracle",
    "ninjutsu", "prowl", "transmute", "scavenge", "encore", "outlast",
}

_BARE_KEYWORD = re.compile(r"[A-Za-z][A-Za-z'’ -]*(?:\s*\{[^}]*\})*")

#the same keyword with its cost written out after a dash rather than printed as
#mana symbols, eg "Cycling—Pay 2 life"
_DASH_COST = re.compile(r"[A-Za-z][A-Za-z'’ ]*(?:\s*\{[^}]*\})*\s*[–—]\s*\S")


def reminder_is_the_rule(stripped):
    text = stripped.strip().rstrip(".")
    if not text:
        return False
    first = re.split(r"[^A-Za-z'’-]", text, maxsplit=1)[0].lower()
    if first not in REMINDER_KEYWORDS:
        return False
    if ". " not in text and _DASH_COST.match(text):
        return True
    for part in text.split(","):
        part = part.strip()
        if part and not _BARE_KEYWORD.fullmatch(part):
            return False
    return True


def clean_line(line, card_name):
    stripped = re.sub(r"\(.*?\)", "", line)
    if reminder_is_the_rule(stripped):
        line = line.replace("(", "").replace(")", "")
    else:
        line = stripped
    #flavour prefixes, exactly as the ingest strips them: table rows ("1—9 |"),
    #saga chapters, and scryfall's catalog of words before a dash
    line = re.sub(r"^\d+(?:\s*[-–—]\s*\d+|\+)?\s*\|\s*", "", line)
    line = re.sub(r"^[IVX]+(?:, [IVX]+)*\s+—\s+", "", line)
    m = re.match(r"^([^—•|]{1,40}?)\s+—\s+(?=\S)", line)
    if m and m.group(1) in PREFIX_WORDS:
        line = line[m.end():]
    line = line.replace(card_name, "this card")
    if "," in card_name:
        line = line.replace(card_name.split(",")[0], "this card")
    return line.strip()


#a homemade idf: without it every flying creature matches every other at 100%.
#
#nothing is punished until a line is on more than 5 cards. punishing from 2
#buries the BEST results: a line shared by two cards means somebody printed a
#functional reprint, and that reprint is the match people came for
def line_weight(count):
    if count <= 5:
        return 1.0
    return 1.0 / (1.0 + math.log10(count / 5.0))


#trying a new embedding model stops being a one way door: new vectors go into
#embedding_v2, this flips the site over, and unsetting it flips straight back.
#
#the value lands INSIDE SQL STRINGS, so it is checked against a fixed list rather
#than trusted: otherwise a typo in a railway variable is an injection point on
#every search.
#above the calibration because load_calibration reads it
EMBED_COLUMNS = ("embedding", "embedding_v2")


def embed_column():
    col = os.environ.get("EMBED_COLUMN", "").strip() or "embedding"
    if col not in EMBED_COLUMNS:
        raise ValueError("EMBED_COLUMN must be one of " + ", ".join(EMBED_COLUMNS))
    return col


EMBED_COL = embed_column()


#the raw cosine lives in a compressed band, so this map turns it into the percent
#the site shows and the gate is written in DISPLAYED units.
#
#this and MECH_CALIBRATION are SEEDS: the ingest writes the real maps into meta
#beside the model they are anchored to, and load_calibration makes the database's
#word win. these hold only until the first ingest run
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


#raw cosine is arbitrary per model, so the displayed percent is pinned to judged
#pairs. the anchors are documented beside EMBED_MODEL in ingest/update.py, which
#is the source of truth that lands in meta
MECH_CALIBRATION = [(0.0, 0), (0.30, 30), (0.42, 45), (0.62, 65), (0.76, 80), (0.90, 92), (1.0, 100)]


#has the database actually been asked yet? the load runs once at import, so a
#boot during a database blip would pin the SEED maps for the life of the worker:
#silent, and lasting until the next redeploy. the app retries off this flag, so a
#blip costs one request's worth of seeds rather than a deploy's
CALIBRATED = False


def load_calibration():
    #meta's maps replace the seeds, so the percents always belong to the model
    #that made the vectors. a database the ingest never ran against has no meta
    #rows and the seeds hold.
    #
    #a TRIAL COLUMN needs its own map or every percent is a lie: cosines sit in a
    #different band per model, and the shared meta row belongs to whichever model
    #filled lines.embedding. without the suffix a near verbatim match reads 62%
    #under a trial model where the refit puts it at 77%
    global CALIBRATION, MECH_CALIBRATION, CALIBRATED
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
        #reaching here means the database ANSWERED, possibly "no such rows",
        #which is a virgin database and a real answer
        CALIBRATED = True
    except Exception:
        pass


load_calibration()


def mech_display(raw):
    raw = max(0.0, min(1.0, raw))
    for (x0, y0), (x1, y1) in zip(MECH_CALIBRATION, MECH_CALIBRATION[1:]):
        if raw <= x1:
            return round(y0 + (y1 - y0) * (raw - x0) / (x1 - x0))
    return 100
