#builds keyword -> meaning training pairs out of scryfall reminder text, so
#the model can learn that "Hexproof" and "Shroud" are cousins instead of two
#random english words. wizards maintain the definitions, and every keyword
#ships with reminder text on some card or another.
#
#has to download the raw bulk file, the site database strips reminder text
#before storing lines. writes finetune/train_keywords.jsonl:
#    python finetune/make_keywords.py

import os
import re
import sys
import json

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
#two levels up, because this lives in legacy/ and still needs the repo root
#on the path to reach common/
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from common.cards import HEADERS, keep_card, get_text, bulk_uri, read_bulk

import requests

#train_keywords.jsonl belongs to --objective lines, so it is written into
#legacy/traindata beside this script. train.py looks in both folders, so a
#regenerated file is still found
OUT_DIR = os.path.dirname(os.path.abspath(__file__))

#a keyword line is a short phrase, maybe a cost, then reminder text in parens
#("Hexproof (This creature...)", "Ward {2} (Whenever...)", "Cumulative upkeep {1} (...)")
KEYWORD_LINE = re.compile(r"^([A-Z][A-Za-z'— -]{0,30}?(?: \{[^}]+\})*) \(([^)]+)\)$")


def main():
    print("downloading the scryfall bulk file...")
    bulk = None
    for item in requests.get("https://api.scryfall.com/bulk-data", headers=HEADERS, timeout=120).json()["data"]:
        if item["type"] == "oracle_cards":
            bulk = item
    #gzipped json lines, so it lands on disk and read_bulk walks it
    path = os.path.join(OUT_DIR, "oracle-cards.jsonl.gz")
    with requests.get(bulk_uri(bulk), headers=HEADERS, timeout=300, stream=True) as r:
        r.raise_for_status()
        with open(path, "wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 1024):
                f.write(chunk)

    #count every (keyword phrase, reminder) sighting so the most common
    #reminder wording wins for each keyword
    sightings = {}
    for c in read_bulk(path):
        if not keep_card(c):
            continue
        for line in get_text(c).split("\n"):
            m = KEYWORD_LINE.match(line.strip())
            if not m:
                continue
            kw, reminder = m.group(1).strip(), m.group(2).strip()
            #keyword phrases are short, ability words and full sentences arent
            if len(kw.split()) > 4 or kw.endswith("."):
                continue
            sightings.setdefault(kw, {})
            sightings[kw][reminder] = sightings[kw].get(reminder, 0) + 1

    pairs = []
    for kw in sorted(sightings):
        counts = sightings[kw]
        total = sum(counts.values())
        if total < 3:
            continue  #one-off matches are usually parser noise, not keywords
        best = max(counts, key=counts.get)
        pairs.append({"anchor": kw, "positive": best, "why": "keyword reminder", "seen": total})

    data_dir = os.path.join(OUT_DIR, "traindata")
    os.makedirs(data_dir, exist_ok=True)
    path = os.path.join(data_dir, "train_keywords.jsonl")
    with open(path, "w", encoding="utf-8") as f:
        for p in pairs:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")
    print("wrote " + str(len(pairs)) + " keyword pairs -> " + path)
    for p in pairs[:15]:
        print("  " + p["anchor"] + "  ->  " + p["positive"][:70])


if __name__ == "__main__":
    main()
