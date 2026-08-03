#card handling helpers shared between the web app and the update pipeline

import re
import gzip
import json

from common.prefix_words import PREFIX_WORDS

#scryfall's docs say to send a real user agent with api requests
HEADERS = {"User-Agent": "Delvefall/1.0 (personal project)", "Accept": "application/json"}


def bulk_uri(item):
    #through one function rather than by key at four call sites, the key name
    #being scryfall's to rename
    return item["jsonl_download_uri"]


def bulk_size(item):
    return item.get("compressed_size", 0)


def read_bulk(path):
    #gzipped json lines. the body IS the gzip rather than a gzip
    #content-encoding, so nothing decompresses it in transit and it lands on
    #disk still compressed.
    #
    #a generator because default_cards is a couple of gigabytes opened up
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)

#layouts that arent actual playable cards
SKIP_LAYOUTS = ["token", "double_faced_token", "emblem", "art_series", "planar", "scheme", "vanguard"]


def get_text(card):
    #double faced cards keep their text on the faces instead of the card itself
    if card.get("oracle_text"):
        return card["oracle_text"]
    if "card_faces" in card:
        parts = []
        for face in card["card_faces"]:
            if face.get("oracle_text"):
                parts.append(face["oracle_text"])
        return "\n".join(parts)
    return ""


def can_command(card):
    """Can this card be somebody's commander?

    Four ways in, checked against scryfall's own is:commander over the whole
    pool: it agrees on all 3609 of them bar Grist, the Hunger Tide, which is a
    creature in every zone except the battlefield and says so in words no
    predicate should try to read.

    THE FRONT FACE decides, always. a transform card's type_line carries both
    faces joined by //, and the back being legendary is nothing to do with who
    can lead a deck: Akki Lavarunner // Tok-Tok, Volcano Born is not a commander.

    the PRINTED POWER is what makes a legendary Vehicle or Spacecraft eligible,
    and it is not optional to check: of the 36 legendary vehicles and spacecraft
    in the pool, the 33 with a printed power are commanders and the 3 without
    (The Eternity Elevator among them) are not. a type line alone cannot tell
    them apart.
    """
    faces = card.get("card_faces") or []
    front = faces[0] if faces else card
    #the type line is the CARD's on most layouts and the face's on split ones
    types = (front.get("type_line") or card.get("type_line") or "")
    front_types = types.split("//")[0]
    if "Legendary" not in front_types:
        return False
    if "Creature" in front_types:
        return True
    #a Background is only ever half of a pair, and is still a commander
    if "Background" in front_types:
        return True
    if front.get("power") is not None or (not faces and card.get("power") is not None):
        return True
    return "can be your commander" in (get_text(card) or "").lower()


def get_image(card):
    if "image_uris" in card:
        return card["image_uris"].get("normal", "")
    if "card_faces" in card and "image_uris" in card["card_faces"][0]:
        return card["card_faces"][0]["image_uris"].get("normal", "")
    return ""


def get_back_image(card):
    #split and adventure cards have two faces too, but share one picture, so
    #only genuinely double faced layouts carry per-face image_uris
    faces = card.get("card_faces")
    if faces and len(faces) > 1 and "image_uris" in faces[1]:
        return faces[1]["image_uris"].get("normal", "")
    return ""


#mechanics whose reminder text is the rule. stripping the parens stored Cyclonic
#Rift as a plain one-target bounce spell, matching Perilous Voyage at 91% and
#missing the one-sided wipe that makes the card worth $30.
#
#the bar for adding one: it prints its reminder on nearly all its lines, so the
#population moves together rather than splitting in half. evergreen abilities
#fail it (3119 bare "Flying" lines against the 3% that spell it out, equip 242
#with against 332 without) and stay stripped
REMINDER_KEYWORDS = {
    "overload", "cascade", "storm", "cycling", "flashback", "morph", "disguise",
    "madness", "convoke", "delve", "buyback", "entwine", "replicate", "embalm",
    "eternalize", "unearth", "disturb", "blitz", "bargain", "craft", "mutate",
    "foretell", "bestow", "improvise", "emerge", "evoke", "dash", "spectacle",
    "surge", "escalate", "splice", "rebound", "conspire", "retrace", "miracle",
    "ninjutsu", "prowl", "transmute", "scavenge", "encore", "outlast",
}

#one keyword name plus any mana symbols, eg "Cycling {2}" or "Flying"
_BARE_KEYWORD = re.compile(r"[A-Za-z][A-Za-z'’ -]*(?:\s*\{[^}]*\})*")

#a cost spelled out after a dash rather than printed as mana symbols, eg
#"Cycling—Pay 2 life". what follows the dash is the price of the keyword and not
#what it does, so the rule is still only in the parens. 56 lines, 16 keywords
_DASH_COST = re.compile(r"[A-Za-z][A-Za-z'’ ]*(?:\s*\{[^}]*\})*\s*[–—]\s*\S")


def reminder_is_the_rule(stripped):
    text = stripped.strip().rstrip(".")
    if not text:
        return False
    first = re.split(r"[^A-Za-z'’-]", text, maxsplit=1)[0].lower()
    if first not in REMINDER_KEYWORDS:
        return False
    #". " means a sentence follows the cost, and a sentence is meaning rather
    #than a price: Visions of Glory's "Flashback {8}{W}{W}. This spell costs {X}
    #less to cast this way" says what it does
    if ". " not in text and _DASH_COST.match(text):
        return True
    for part in text.split(","):
        part = part.strip()
        if part and not _BARE_KEYWORD.fullmatch(part):
            return False
    return True


def clean_line(line, card_name):
    #reminder text is for humans, the model doesnt need it, except where the
    #parens hold the whole rule
    stripped = re.sub(r"\(.*?\)", "", line)
    if reminder_is_the_rule(stripped):
        line = line.replace("(", "").replace(")", "")
    else:
        line = stripped
    #flavour prefixes must not beat meaning (testing_list CA). the word list is
    #scryfall's own catalogs, so keywords that genuinely use the dash (Boast,
    #Companion) stay whole.
    #
    #the row pattern reads four shapes because scryfall prints four, across the
    #150 table rows in the pool:
    #    75  "1—9 |"    an em dash range
    #    47  "10+ |"    a spacecraft's station thresholds
    #    26  "20 |"     a bare number, the top of a d20 table
    #     2  "1-9 |"    a plain hyphen range
    #miss one and "8+ | Flying, deathtouch" embeds as its own unique line,
    #drawing full idf weight for an ability two and a half thousand cards share
    line = re.sub(r"^\d+(?:\s*[-–—]\s*\d+|\+)?\s*\|\s*", "", line)
    line = re.sub(r"^[IVX]+(?:, [IVX]+)*\s+—\s+", "", line)
    m = re.match(r"^([^—•|]{1,40}?)\s+—\s+(?=\S)", line)
    if m and m.group(1) in PREFIX_WORDS:
        line = line[m.end():]
    #a name left in makes the model think names matter. legendaries also shorten
    #to their first name mid-text ("Jacob, the Great" -> "Jacob")
    line = line.replace(card_name, "this card")
    if "," in card_name:
        line = line.replace(card_name.split(",")[0], "this card")
    return line.strip()


def keep_card(card):
    #oracle_id is the primary key, so a card without one cannot be stored
    if not card.get("oracle_id"):
        return False
    if card.get("set_type") in ("funny", "memorabilia"):
        return False  #skip the joke sets
    if card.get("layout") in SKIP_LAYOUTS:
        return False
    if card.get("digital") and card.get("legalities", {}).get("vintage", "not_legal") == "not_legal":
        #the vintage check is what keeps this from eating real cards: scryfall
        #sometimes picks a digital printing to represent a paper one (ancestral
        #recall arrives as vintage masters, an mtgo set), and every paper card is
        #at least restricted in vintage. arena-only cards are not_legal and drop
        return False
    if not get_text(card).strip():
        return False  #vanilla creatures, basic lands etc, nothing to compare
    return True


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
