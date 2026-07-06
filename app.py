#the actual website. run build_index.py first or this will just crash

import json
import math
import difflib
from collections import Counter

import numpy as np
from flask import Flask, render_template, request

app = Flask(__name__)

print("loading the index, give it a sec...")
with open("index.json", encoding="utf-8") as f:
    data = json.load(f)
cards = data["cards"]
lines = data["lines"]
line_owner = data["line_owner"]
embeddings = np.load("embeddings.npy")
print("loaded " + str(len(cards)) + " cards / " + str(len(lines)) + " lines of text")

#which rows of the embedding matrix belong to which card
card_lines = {}
for row, owner in enumerate(line_owner):
    if owner not in card_lines:
        card_lines[owner] = []
    card_lines[owner].append(row)

#lowercase name -> where that card sits in the list, for the fuzzy matching
name_index = {}
for i, c in enumerate(cards):
    name_index[c["name"].lower()] = i

#lines like "Flying" appear on thousands of cards, and if we don't do anything
#about it every flying creature "matches" every other flying creature at 100%
#and the results are useless. so common lines get weighted down when ranking.
#basically a homemade version of idf from search engines
line_counts = Counter(lines)


def line_weight(line):
    return 1.0 / (1.0 + math.log(line_counts[line]))


def find_card(query):
    q = query.lower().strip()
    #exact match first, then startswith, then anywhere in the name
    for i, c in enumerate(cards):
        if c["name"].lower() == q:
            return i
    for i, c in enumerate(cards):
        if c["name"].lower().startswith(q):
            return i
    for i, c in enumerate(cards):
        if q in c["name"].lower():
            return i
    #last resort, difflib catches close spellings like "lightnig bolt"
    close = difflib.get_close_matches(q, name_index.keys(), n=1, cutoff=0.6)
    if close:
        return name_index[close[0]]
    return None


def find_similar(card_idx, offset=0, how_many=20):
    #the query card's lines are already in the embedding matrix, so we don't
    #even need the model at search time. just compare its rows to everything
    best = {}  #other card idx -> (weighted score, real similarity, our line, their line)
    for row in card_lines.get(card_idx, []):
        w = line_weight(lines[row])
        sims = embeddings @ embeddings[row]  #embeddings are normalized so this is cosine similarity
        #grab way more than we need since a bunch will get filtered/merged
        for k in np.argsort(sims)[::-1][:400]:
            owner = line_owner[k]
            if owner == card_idx:
                continue
            score = float(sims[k]) * w
            if owner not in best or score > best[owner][0]:
                best[owner] = (score, float(sims[k]), lines[row], lines[k])

    ranked = sorted(best.items(), key=lambda x: x[1][0], reverse=True)
    has_more = len(ranked) > offset + how_many

    results = []
    for owner, (score, sim, our_line, their_line) in ranked[offset:offset + how_many]:
        c = cards[owner]
        results.append({
            "name": c["name"],
            "mana_cost": c["mana_cost"],
            "type_line": c["type_line"],
            "image": c["image"],
            "scryfall_uri": c["scryfall_uri"],
            "percent": int(round(sim * 100)),
            "our_line": our_line,
            "their_line": their_line,
        })
    return results, has_more


@app.route("/")
def home():
    query = request.args.get("q", "")
    if not query:
        return render_template("index.html")

    idx = find_card(query)
    if idx is None:
        return render_template("index.html", query=query, not_found=True)

    results, has_more = find_similar(idx)
    return render_template("index.html", query=query, card=cards[idx], results=results, has_more=has_more)


#the load more button on the results page calls this and gets json back
@app.route("/more")
def more():
    query = request.args.get("q", "")
    offset = int(request.args.get("offset", 0))
    idx = find_card(query)
    if idx is None:
        return {"results": [], "has_more": False}
    results, has_more = find_similar(idx, offset)
    return {"results": results, "has_more": has_more}


#the search bar calls this while you type to fill the suggestion dropdown.
#names that start with what you typed come first, then names with it anywhere
@app.route("/suggest")
def suggest():
    q = request.args.get("q", "").lower().strip()
    if len(q) < 2:
        return {"names": []}
    names = []
    for c in cards:
        if c["name"].lower().startswith(q):
            names.append(c["name"])
            if len(names) == 8:
                return {"names": names}
    for c in cards:
        if q in c["name"].lower() and c["name"] not in names:
            names.append(c["name"])
            if len(names) == 8:
                break
    #if substring matching didnt fill the list, fuzzy matching tops it up.
    #difflib scores how close two spellings are so typos still find their card
    if len(names) < 8:
        for m in difflib.get_close_matches(q, name_index.keys(), n=8 - len(names), cutoff=0.6):
            real = cards[name_index[m]]["name"]
            if real not in names:
                names.append(real)
    return {"names": names}


if __name__ == "__main__":
    app.run(debug=True)
