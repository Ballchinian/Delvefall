#card handling helpers shared between the web app and the update pipeline

import re
import gzip
import json

from common.prefix_words import PREFIX_WORDS

#scryfall's docs say to send a real user agent with api requests
HEADERS = {"User-Agent": "Delvefall/1.0 (personal project)", "Accept": "application/json"}


def bulk_uri(item):
    #where one entry of scryfall's bulk-data listing says its file lives. read
    #through here rather than by key, because two ingests and both finetune
    #miners ask the same question and the key name belongs to scryfall
    return item["jsonl_download_uri"]


def bulk_size(item):
    #the download's size in bytes, for the "this will take a while" line
    return item.get("compressed_size", 0)


def read_bulk(path):
    #every object in a downloaded bulk file, one at a time.
    #
    #the files are gzipped json lines: one complete card, or tag, per line. the
    #body is the gzip itself and not a gzip content-encoding, so nothing
    #decompresses it in transit and it lands on disk still compressed.
    #
    #a generator because default_cards is a couple of gigabytes opened up, and
    #line by line means the whole thing never has to be in memory at once
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


def get_image(card):
    if "image_uris" in card:
        return card["image_uris"].get("normal", "")
    if "card_faces" in card and "image_uris" in card["card_faces"][0]:
        return card["card_faces"][0]["image_uris"].get("normal", "")
    return ""


def get_back_image(card):
    #the back face's picture, for the turn-the-card-over button. only double
    #faced layouts carry per-face image_uris (split and adventure cards have
    #two faces too, but those share one picture and land in get_image above)
    faces = card.get("card_faces")
    if faces and len(faces) > 1 and "image_uris" in faces[1]:
        return faces[1]["image_uris"].get("normal", "")
    return ""


#mechanics whose reminder text is the rule. "Overload {6}{U}" says nothing on
#its own, so stripping the parens stored Cyclonic Rift as a plain one-target
#bounce spell and it matched Perilous Voyage at 91%, missing the one-sided
#board wipe that makes the card worth $30.
#
#evergreen abilities are not in here. 2442 cards print a bare "Flying" against
#75 that spell the reminder out, so keeping those 75 would orphan them from the
#other 2442. every keyword in this list is printed with its reminder at least
#~88% of the time, so the whole population moves together instead of splitting
#in half. equip (242 with against 332 without), menace and trample fail that
#test and stay stripped.
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

#a keyword whose cost is spelled out after a dash instead of printed as mana
#symbols: "Cycling—Pay 2 life", "Morph—Discard a card", "Flashback—{1}{U},
#Exile X blue cards from your graveyard". what follows the dash is the price of
#using the keyword, not what the keyword does, so the rule is still only in the
#parens. 56 lines across 16 keywords read this way
_DASH_COST = re.compile(r"[A-Za-z][A-Za-z'’ ]*(?:\s*\{[^}]*\})*\s*[–—]\s*\S")


def reminder_is_the_rule(stripped):
    #true when removing the parens left nothing but keyword names, mana symbols
    #and costs ("Cycling {2}", "Cycling—Pay 2 life", "Flying, double strike")
    #AND the leading keyword is one whose reminder text carries the actual rule.
    #anything with a real sentence in it kept its meaning and doesnt need the
    #reminder back
    text = stripped.strip().rstrip(".")
    if not text:
        return False
    first = re.split(r"[^A-Za-z'’-]", text, maxsplit=1)[0].lower()
    if first not in REMINDER_KEYWORDS:
        return False
    #a cost written as words. ". " means a sentence follows the cost, and a
    #sentence is meaning rather than a price: Visions of Glory's "Flashback
    #{8}{W}{W}. This spell costs {X} less to cast this way" says what it does
    if ". " not in text and _DASH_COST.match(text):
        return True
    for part in text.split(","):
        part = part.strip()
        if part and not _BARE_KEYWORD.fullmatch(part):
            return False
    return True


def clean_line(line, card_name):
    #reminder text (the stuff in parens) is just for humans, the model doesnt
    #need it - except where the parens hold the whole rule, see above
    stripped = re.sub(r"\(.*?\)", "", line)
    if reminder_is_the_rule(stripped):
        line = line.replace("(", "").replace(")", "")
    else:
        line = stripped
    #flavour prefixes must not beat meaning (testing_list CA): table rows
    #("10-19 |", "12+ |"), saga chapter markers ("I, II —") and ability/flavor
    #words ("Landfall —", "Siege Monster —") say when or in what style, not
    #what happens, so they go. the word list is scryfall's own catalogs, so
    #keywords that genuinely use the dash (Boast, Companion) stay whole.
    #
    #the row pattern reads four shapes because scryfall prints four. measured
    #over the 150 table rows in the pool:
    #    75  "1—9 |"    an em dash range, the commonest by far
    #    47  "10+ |"    a spacecraft's station thresholds
    #    26  "20 |"     a bare number, the top of a d20 table
    #     2  "1-9 |"    a plain hyphen range
    #miss one and its rows keep their prefix: "8+ | Flying, deathtouch" embeds
    #as its own text instead of joining the two and a half thousand cards that
    #just say flying, drawing the full idf weight of a unique line for an ability
    #thousands of cards share
    line = re.sub(r"^\d+(?:\s*[-–—]\s*\d+|\+)?\s*\|\s*", "", line)
    line = re.sub(r"^[IVX]+(?:, [IVX]+)*\s+—\s+", "", line)
    m = re.match(r"^([^—•|]{1,40}?)\s+—\s+(?=\S)", line)
    if m and m.group(1) in PREFIX_WORDS:
        line = line[m.end():]
    #cards refer to themselves by name, which would make the model think names
    #matter. swap it for something generic. legendary cards also get shortened
    #to their first name in the middle of the text ("Jacob, the Great" -> "Jacob")
    #so handle that too
    line = line.replace(card_name, "this card")
    if "," in card_name:
        line = line.replace(card_name.split(",")[0], "this card")
    return line.strip()


def keep_card(card):
    #everything that isnt a real playable paper card goes. oracle_id is the
    #primary key in the database, so a card without one cannot be stored
    if not card.get("oracle_id"):
        return False
    if card.get("set_type") in ("funny", "memorabilia"):
        return False  #skip the joke sets
    if card.get("layout") in SKIP_LAYOUTS:
        return False
    if card.get("digital") and card.get("legalities", {}).get("vintage", "not_legal") == "not_legal":
        #arena/mtgo only cards (alchemy rebalances etc), never printed in paper.
        #the vintage check matters: scryfall sometimes picks a digital printing
        #to represent a real paper card (ancestral recall arrives as vintage
        #masters, an mtgo set), and every real paper card is at least restricted
        #or banned in vintage, so those stay. true digital-only cards are
        #not_legal there and still get dropped
        return False
    if not get_text(card).strip():
        return False  #vanilla creatures, basic lands etc, nothing to compare
    return True


def split_lines(card):
    #each line of rules text is basically one ability, so embed every line
    #separately instead of whole cards. that way one matching ability is
    #enough. every line remembers which face printed it (0 front, 1 back),
    #so a match that lives on the back face can show that side of the card
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
