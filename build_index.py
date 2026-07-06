#downloads every magic card from scryfall and builds the similarity index. (runs once)

import os
import re
import json
import requests

import numpy as np   
#Library for fast math on big grids of number

from sentence_transformers import SentenceTransformer

CARDS_FILE = "cards.json"

#scryfall's docs say to send a real user agent with api requests
HEADERS = {"User-Agent": "MTGSimilarCards/0.1 (personal project)", "Accept": "application/json"}

#layouts that arent actual playable cards
SKIP_LAYOUTS = ["token", "double_faced_token", "emblem", "art_series", "planar", "scheme", "vanguard"]


def download_cards():
    print("asking scryfall where the bulk file lives...")
    r = requests.get("https://api.scryfall.com/bulk-data", headers=HEADERS)
    r.raise_for_status()
    url = None
    for item in r.json()["data"]:
        #oracle_cards = one entry per unique card instead of every single printing
        if item["type"] == "oracle_cards":
            url = item["download_uri"]
    print("downloading " + url)
    print("(its like 180mb so this can take a minute)")
    r = requests.get(url, headers=HEADERS)
    with open(CARDS_FILE, "wb") as f:
        f.write(r.content)
    print("saved to " + CARDS_FILE)


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


def clean_line(line, card_name):
    #reminder text (the stuff in parens) is just for humans, the model doesnt need it
    line = re.sub(r"\(.*?\)", "", line)
    #cards refer to themselves by name, which would make the model think names
    #matter. swap it for something generic. legendary cards also get shortened
    #to their first name in the middle of the text ("Jacob, the Great" -> "Jacob")
    #so handle that too
    line = line.replace(card_name, "this card")
    if "," in card_name:
        line = line.replace(card_name.split(",")[0], "this card")
    return line.strip()


def main():
    if not os.path.exists(CARDS_FILE):
        download_cards()
    else:
        print("already have " + CARDS_FILE + ", delete it if you want fresh data")

    print("loading cards...")
    with open(CARDS_FILE, encoding="utf-8") as f:
        all_cards = json.load(f)
    print("scryfall gave us " + str(len(all_cards)) + " cards")

    cards = []
    for c in all_cards:
        if c.get("set_type") in ("funny", "memorabilia"):
            continue  #skip the joke sets
        if c.get("layout") in SKIP_LAYOUTS:
            continue
        if not get_text(c).strip():
            continue  #vanilla creatures, basic lands etc, nothing to compare
        cards.append(c)
    print("kept " + str(len(cards)) + " real cards that have rules text")

    #each line of rules text is basically one ability, so embed every line
    #separately instead of whole cards. that way one matching ability is enough
    lines = []
    line_owner = []  #lines[i] belongs to cards[line_owner[i]]
    for i, c in enumerate(cards):
        for line in get_text(c).split("\n"):
            cleaned = clean_line(line, c["name"])
            if len(cleaned) < 3:
                continue
            lines.append(cleaned)
            line_owner.append(i)
    print(str(len(lines)) + " lines of card text to embed")

    print("loading the model (downloads ~90mb the very first time)...")
    model = SentenceTransformer("all-MiniLM-L6-v2")
    print("embedding everything, this is the slow part...")
    embs = model.encode(lines, batch_size=128, show_progress_bar=True, normalize_embeddings=True)
    np.save("embeddings.npy", embs)

    #only keep the fields the site actually needs so we're not lugging 180mb around
    slim = []
    for c in cards:
        slim.append({
            "name": c["name"],
            "mana_cost": c.get("mana_cost", ""),
            "type_line": c.get("type_line", ""),
            "text": get_text(c),
            "image": get_image(c),
            "scryfall_uri": c.get("scryfall_uri", ""),
        })
    with open("index.json", "w", encoding="utf-8") as f:
        json.dump({"cards": slim, "lines": lines, "line_owner": line_owner}, f)

    print("done! run app.py now")


if __name__ == "__main__":
    main()
