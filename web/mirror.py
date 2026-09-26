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
import time

from db import HOOK_WAIT, pool
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
    #both halves of a " // " name, stripped one at a time, exactly as the ingest
    #strips them. the spaces keep SP//dr, Piloted by Peni in one piece, and an
    #empty part is skipped because /custom's name field is optional
    for part in card_name.split(" // "):
        if not part:
            continue
        line = line.replace(part, "this card")
        if "," in part:
            line = line.replace(part.split(",")[0], "this card")
    return line.strip()


def split_lines(card):
    #one line of rules text is roughly one ability, so embedding per line means
    #one matching ability is enough. the face index (0 front, 1 back) rides
    #along so a match on the back can show that side of the card
    if card.get("oracle_text"):
        chunks = [(card["oracle_text"], 0)]
    else:
        chunks = [(f.get("oracle_text", ""), i) for i, f in enumerate(card.get("card_faces", []))]
    out = []
    for text, face in chunks:
        for line in text.split("\n"):
            cleaned = clean_line(line, card["name"])
            if len(cleaned) < 3:
                continue
            out.append((cleaned, min(face, 1)))
    return out


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

#what schema.sql declares lines.embedding as. here only so /admin can say
#whether the live column matches it: converting the column is a job that runs by
#hand, out of line with the site up, and nothing else would notice it was owed
EMBED_TYPE = "halfvec(768)"


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

#a model swap writes new maps into meta and does NOT redeploy web, which railway
#ships on /web/** only, so a worker that reads once serves the new model's vectors
#through the old model's map. that is silent and site wide: a near verbatim match
#reads 62% where the refit puts it at 77%. five minutes is about 288 reads of two
#rows a day per worker
RELOAD_EVERY = 300.0

#set by every load ATTEMPT and not just the ones that answer, so a database that
#is down costs one read per interval rather than one per request. the flag above
#is what retries a boot that found nothing
_LOADED_AT = 0.0


def load_calibration(wait=None):
    #meta's maps replace the seeds, so the percents always belong to the model
    #that made the vectors. a database the ingest never ran against has no meta
    #rows and the seeds hold.
    #
    #a TRIAL COLUMN needs its own map or every percent is a lie: cosines sit in a
    #different band per model, and the shared meta row belongs to whichever model
    #filled lines.embedding. without the suffix a near verbatim match reads 62%
    #under a trial model where the refit puts it at 77%
    global CALIBRATION, MECH_CALIBRATION, CALIBRATED, _LOADED_AT
    _LOADED_AT = time.monotonic()
    suffix = "" if EMBED_COL == "embedding" else "_" + EMBED_COL
    try:
        got = {}
        with pool.connection(timeout=wait) as conn:
            for key in ("concept_calibration", "mech_calibration"):
                row = None
                if suffix:
                    row = conn.execute("SELECT value FROM meta WHERE key = %s",
                                       (key + suffix,)).fetchone()
                if row is None:
                    row = conn.execute("SELECT value FROM meta WHERE key = %s", (key,)).fetchone()
                if row:
                    got[key] = [(float(x), float(y)) for x, y in json.loads(row["value"])]
        #both or neither: a read that dies after the first map would leave one
        #model's concept map beside the other's mech map until the next reload
        CALIBRATION = got.get("concept_calibration", CALIBRATION)
        MECH_CALIBRATION = got.get("mech_calibration", MECH_CALIBRATION)
        #reaching here means the database ANSWERED, possibly "no such rows",
        #which is a virgin database and a real answer
        CALIBRATED = True
    except Exception:
        pass


def refresh_calibration():
    #the flag first, so a worker that booted during a database blip still retries
    #on every request until it gets an answer. then the timer, which is the only
    #thing that notices a model swap: nothing else restarts web.
    #
    #gunicorn runs 4 threads a worker, so two requests can pass this together. the
    #timestamp is set before the read rather than after, so the worst a race costs
    #is one extra read of two rows
    if not CALIBRATED or time.monotonic() - _LOADED_AT >= RELOAD_EVERY:
        load_calibration(HOOK_WAIT)


load_calibration()


def mech_display(raw):
    raw = max(0.0, min(1.0, raw))
    for (x0, y0), (x1, y1) in zip(MECH_CALIBRATION, MECH_CALIBRATION[1:]):
        if raw <= x1:
            return round(y0 + (y1 - y0) * (raw - x0) / (x1 - x0))
    return 100
