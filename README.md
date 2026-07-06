# Cardalike

A web app that finds Magic: The Gathering cards that do similar things to the card you search for. Not cards that share words, and not "cards that go in the same deck", but cards whose abilities mean the same thing even when the wording is completely different, all through a Flask backend that compares sentence embeddings of every line of rules text ever printed.

## Features

- Card search by name with forgiving matching
- Similarity results ranked by best matching line of rules text
- Every result shows the exact line that matched and a similarity percent
- Load more button that pulls the next 20 results without a page reload
- Scryfall styled interface with card images linking back to Scryfall

## How it works

The heavy lifting happens once, up front. `build_index.py` downloads every card and turns their rules text into vectors. The Flask app answers searches by comparing vectors that already exist, so the language model never runs while the site is up and searches come back in well under a second.

### Card data

Card data comes from Scryfall's bulk data API, which publishes a daily "Oracle Cards" file with exactly one entry per unique card (Scryfall asks tools to use this instead of scraping pages). Requests send a custom User Agent like their docs require. Cards are filtered before indexing:

| Filter | Why |
| --- | --- |
| Joke sets (funny / memorabilia) | Not real cards |
| Tokens, emblems, art cards, schemes | Not playable cards |
| No rules text | Vanilla creatures and basic lands have nothing to compare |

Delete `cards.json` and rerun the build whenever you want fresh card data.

### Text cleaning

Each line of a card's rules text is treated as one ability, so lines get embedded separately and one matching ability is enough. Before embedding, every line is cleaned: reminder text in parentheses is stripped, and the card's references to its own name are swapped for "this card" so names can't influence matching (including the shortened first name that legendary cards use mid sentence).

### Embeddings

Every cleaned line goes through the `all-MiniLM-L6-v2` sentence transformer, which turns text into a normalized vector of 384 numbers where lines that mean similar things land close together. That is what lets "you may draw a card unless that player pays {4}" match "they may pay {1}. If the player does, they draw a card". The vectors land in `embeddings.npy` and a slimmed down card list in `index.json`.

### Ranking

A search looks up the card, compares each of its lines against every line in the index (a dot product, which equals cosine similarity because the vectors are normalized), and keeps each candidate card's best matching pair. Common lines get weighted down so they don't drown out the interesting matches:

| Line | Rough count | Effect on ranking |
| --- | --- | --- |
| "Flying" | Thousands of cards | Heavily downweighted |
| A wordy triggered ability | A handful of cards | Counts nearly full strength |

The weight is a homemade IDF, `1 / (1 + log(count))`. The percent shown on results is the raw similarity; the weight only affects ordering.

### Load more

Results come 20 at a time. The Load 20 more button calls the `/more` endpoint with an offset, gets the next batch back as JSON, and appends the cards to the grid. Once the server reports nothing left, the button removes itself.

## Tech stack

- **Backend:** Python / Flask
- **Frontend:** Jinja templates + vanilla JavaScript
- **Similarity:** sentence-transformers (`all-MiniLM-L6-v2`) with NumPy
- **Card data:** Scryfall bulk data (Oracle Cards)

## A typical search

1. Type a card name into the search bar.
2. The card appears with its image and full rules text.
3. Below it, the 20 closest cards show up, each with the line of text that matched and how close it was.
4. Hover a matched line to see which of your card's lines it paired with.
5. Load 20 more keeps digging deeper into the rankings, and clicking any card opens it on Scryfall.
