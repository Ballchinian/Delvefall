# Delvefall

A web app that finds Magic: The Gathering cards similar to the card you search for. You type a card name and that is the whole cost: no query language to learn, no vocabulary to look up first. Underneath, it compares sentence embeddings of every line of rules text ever printed, so it finds abilities that mean the same thing even when the wording is completely different, rather than cards that share words or cards that go in the same deck.

## Features

**Search and results**

- Card search by name with forgiving matching, plus an autocomplete dropdown
- Results ranked by best matching line of rules text, each showing the exact line that matched and a similarity percent
- A card that matches several of your card's lines says so ("+2 more matching lines")
- Load more pulls the next 20 results without a page reload
- Results below 70% wait behind a button that opens them ten points at a time, labelled in words ("weaker matches", then "weaker still"). Every reload starts back at the strong matches
- Sort by best match, price (dollars, euros or approximate pounds, refreshed daily), how much a card gets played (EDHREC rank, most or least), salt, or card age, each in either direction

**The two axes**

- Every result is scored twice and averaged: once on rules text, once on concepts (the community tags the card carries). Hovering the badge breaks it back into its two halves. There is no slider, because testing settled it: an even split beat every other setting, including both ends
- Line picker: click any of the searched card's rules lines to search just that ability, or combine several. The URL stays shareable
- Tag picker: click a tag to switch it off. The tags it implied go with it and the score is renormalized over what is left, so the percent keeps meaning what it always meant
- **Picking a line narrows the tags to that one ability**, which neither Scryfall nor Tagger can do, since both are card-level. The narrowing is inferred, so the page says so, faded tags click back on, and a wrong one can be reported

**Filters**

- Colour identity in three readings (at most these colours, exactly these, or including these), price range, mana value range, salt range (EDHREC's annual survey of how much players dislike facing a card, 0 to about 3), card types (pick several, any of them matches, so an Artifact Creature answers to both), commanders only, and hide game changers. Cards that aren't commander legal stay hidden unless you tick "include illegal"
- The panel only shows a narrowing filter once you add it, so anything visible in there is being applied and nothing can filter from off screen. The count beside the word Filters answers "is anything narrowing this?" without opening it

**Pages**

- A landing page with the cards you recently searched floating around the search bar. Before you have a history, much-played cards fill the slots
- Unique cards, the counterpart to a random card page: it deals one card nothing else in the game resembles, with the same filters as search and a per-device memory so you are never dealt the same card twice. Each deal draws at random from a small band near the top of what is left, so two people with the same filters get different runs. The dealt cards form a trail with back and forward arrows
- Every card picture gets hover buttons where the physical card needs them: sideways cards (battles, split cards) stay vertical with a rotate button, Kamigawa flip cards flip 180, double faced cards transform. Invasion of Zendikar does all of it at once
- An ink and paper skin, the filter widgets drawn by hand, Scryfall's real mana symbols self hosted, and every card image linking back to Scryfall
- Links unfurl: Open Graph tags on every page, one canonical URL per card, plus breadcrumbs and a sitemap. The sitemap is an index over four parts, the cards split into three bands by how played they are, because Search Console reports coverage per file: split, it says where indexing stops rather than only how much of it there is

**Upkeep**

- Updates itself. A bot checks Scryfall every day and new cards just appear
- Bad results are reportable, and so are bad tags. Reports about filters get answered on the spot; real matching gaps become test cases for the next model

## How it works

Everything lives in a Postgres database with the pgvector extension. The embeddings sit in a `vector(768)` column and the database does the nearest neighbor math itself, so the website is a tiny Flask app that runs a few queries per search. The language model only ever runs inside the update pipeline, never on the server.

| Piece | What it does |
| --- | --- |
| `web/` | The Flask site. Talks to Postgres, needs no torch, no giant files, barely any memory |
| `ingest/` | The update pipeline. Downloads Scryfall's bulk data, embeds whatever is new or changed, writes it to the database |
| `.github/workflows/update.yml` | Runs the pipeline every day on GitHub Actions so the heavy dependencies never go near the web server |

`common/` holds what both sides share: the database schema and the card cleaning helpers. `finetune/` is the embedding model project, with its own README.

`tests/` covers the pure functions: the line cleaner, the filter box compiler, the decklist parser and the calibration maps. It stubs the database out, so it needs no Postgres and runs in under a second:

```
python -m pip install pytest flask flask-compress
python -m pytest tests -q
```

`tests/js/` does the same for the browser modules, on Node's own test runner, so there is nothing to install:

```
node --import ./tests/js/register.mjs --test tests/js/
```

Alongside those sits a regression test per bug that has shipped and been fixed. Those need real rows, so they only run when `TEST_DATABASE_URL` points at a **throwaway** Postgres with pgvector (never the live one, the fixture writes). Without it they skip and the rest of the suite still runs:

```
TEST_DATABASE_URL=postgresql://... python -m pytest tests -q
```

`.github/workflows/check.yml` runs all of it on every push, alongside compiling every Python and JS file and checking that the copies in `web/` still match their sources. Railway deploys `main` on push, so that workflow is the gate in front of a deploy.

### The database

Fourteen tables, in four groups.

**The search needs five.** `cards` has one row per unique card, keyed by Scryfall's `oracle_id` (stable across every printing), including the filter columns: colour identity, USD and EUR prices, mana value, the official Commander game changer flag, commander legality, EDHREC rank, EDHREC salt score and first printing date. `lines` has one row per line of rules text with its embedding. `line_stats` counts how many cards share each line, for the ranking weights. `meta` remembers which Scryfall bulk file was processed last and which model made the vectors. `feedback` holds user reports.

**Four carry the concepts axis.** `tags` is Scryfall Tagger's tag tree with an IDF weight derived from how many cards carry each one, `card_tags` links cards to tags (rolled up the tree, inherited links damped), `card_tag_norms` bakes each card's vector length so the scoring queries stay cheap, and `line_tags` is the inferred answer to which of a card's tags belongs to which of its lines.

**Two** hold the population the deck lens ranks a pasted list against: `decks` and `deck_cards`, the preconstructed Commander decks from MTGJSON.

**Three** count visitors without keeping anything that points back at one: `visit_salt` holds the day's secret, `visit_seen` the one way fingerprints made with it, and `visit_daily` the frozen number that is all that survives the day.

Two derived columns power the unique cards page. `lines.nn_sim` is each line's nearest neighbor similarity (how close the closest line on any *other* card gets), and `cards.uniqueness` is 1 minus the card's most isolated line's `nn_sim`, so a card with Flying plus one ability nobody else has still counts as unique. The ingest recomputes them from scratch whenever lines change, never incrementally: a new card can make an old card less unique and a deleted card can make its neighbors more unique, so patching only changed rows would quietly rot the scores. The all-pairs math runs as one numpy matrix multiply on the Actions runner (about a minute) instead of ~31k pgvector scans against a busy production database (hours).

Prices are the cheapest paper printing in any finish, found by streaming Scryfall's Default Cards file (every printing, a couple of gigabytes) through ijson each day. Digital printings, oversized promos and gold border world championship decks don't count, you can't sleeve those up. A switch on the filters panel flips every price on the page, and the price bounds and sorts follow it, so what you filter on is always the number you see. Pounds are derived rather than sourced, and labelled approximate because of it: Scryfall quotes dollars and euros only, so the pound figure converts both at the day's ECB reference rates and takes the middle. The rate fetch is cached for a day and seeded with a fallback pair, so an outage at the rate API can never break a page.

The nearest neighbor scans walk an HNSW index, which turned 200-250ms of vector math per line into about 20ms. The build is deliberately denser than pgvector's defaults (m=32, ef_construction=200): common lines put hundreds of identical embeddings into the graph, the default build leaves those clusters badly connected, and a 94% match once fell out of a top-400 scan because of it. The dense build measured zero misses above 0.90 similarity against the exact scan. Searches use pgvector's iterative scan in strict order, so a heavily filtered search keeps walking the graph until it has real answers instead of coming back short.

### Daily updates

The pipeline is built so that doing nothing costs nothing:

1. Ask Scryfall's bulk data API for the Oracle Cards file's `updated_at` timestamp (one tiny request).
2. If it matches the one stored in `meta`, stop. Done in two seconds.
3. Otherwise download the bulk file and hash every card's name + rules text. Cards whose hash matches the database get skipped without embedding anything.
4. Stream the Default Cards file for everything's cheapest printing, and rewrite every card's row regardless, because prices move daily and the game changer list gets edited, and neither shows up in the text hash.
5. Only genuinely new or changed cards (usually a handful, or zero) get their lines embedded and written, all inside one transaction.
6. Rebuild the line counts and save the new timestamp.
7. If any lines changed, recompute the uniqueness scores (always a full recompute, see above).

Running the same pipeline against an empty database seeds the whole thing: everything counts as new and ~61k lines get embedded in one batch. That is the entire initial setup.

Cards that disappear from the bulk file, or that the filters newly exclude, get deleted at the end of the run, so tightening a filter cleans the database up on its own.

### Card data

Card data comes from Scryfall's bulk data API, which publishes a daily "Oracle Cards" file with exactly one entry per unique card (Scryfall asks tools to use this instead of scraping pages). Requests send a custom User Agent as their docs require. Cards are filtered before indexing:

| Filter | Why |
| --- | --- |
| Joke sets (funny / memorabilia) | Not real cards |
| Tokens, emblems, art cards, schemes | Not playable cards |
| Digital only (Alchemy, MTGO exclusives) | Never printed in paper |
| No rules text | Vanilla creatures and basic lands have nothing to compare |

### Text cleaning

Each line of a card's rules text is treated as one ability, so lines are embedded separately and one matching ability is enough. Before embedding, reminder text in parentheses is stripped and the card's references to its own name are swapped for "this card" so names can't influence matching, including the shortened first name legendary cards use mid sentence.

### Embeddings

Every cleaned line goes through a fine tuned EmbeddingGemma model trained specifically on Magic rules text, which turns it into a normalized vector of 768 numbers. Unlike any off the shelf model it knows that "draw a card, then discard a card" and "discard a card: draw a card" are different things, which is what lets "you may draw a card unless that player pays {4}" match "they may pay {1}. If the player does, they draw a card".

The model running now was trained on a different question than the first one. The original learned "these two lines mean the same thing", which is the right target for ranking and the wrong one for saying what a line is ABOUT. The current one learns to put a line next to the words of the tags it carries, trained on the eleven thousand cards whose entire rules text is a single line, where every tag a human typed belongs to that one line with no inference needed. That moved the tag half of the site from 47% to 78% on the exam that matters and line attribution from 88% to 94% precision, while holding its ground on the older line-to-line test, which is the one that would have caught it forgetting what it already knew. `finetune/README.md` is the full account.

### Ranking

A search grabs the card's own lines, runs a pgvector nearest neighbor query for each (`<=>` is cosine distance, and the vectors are normalized so `1 - distance` is the real similarity), and keeps each candidate card's best matching pair. Common lines get weighted down so they don't drown out the interesting matches:

| Line | Rough count | Effect on ranking |
| --- | --- | --- |
| "Flying" | Thousands of cards | Heavily downweighted |
| A wordy triggered ability | A handful of cards | Counts nearly full strength |

The weight is a homemade IDF that leaves lines on 5 or fewer cards at full strength (a line shared by 2 cards is a functional reprint, exactly the match people came for), then falls off gently: `1 / (1 + log10(count / 5))`. Lines are counted by shape rather than exact text, mana symbols collapsed to a placeholder, because a keyword whose cost varies otherwise splits into one and two card texts that each look unique: Overload is 27 card-lines across 22 different printed costs, so every one drew full weight and Vandalblast matched Dynacharge at 99% on the keyword and nothing else. The percent shown is a calibrated display score, pinned to hand-judged pairs so 80 marks the real quality boundary. The weight only affects ordering.

Results split around a 70% cutoff, which is where a blended score sits, since the badge averages two axes and averages land lower than either half. Everything under it is filed into 10 point bands, and when a tier runs out the load more button offers the next band down by count and by how much worse it is in words, under its own labelled divider. Empty bands are skipped rather than offered and found empty. How deep you have gone lives in one variable on the page and nowhere else, so every reload starts at the strong matches: a sort change, a filter, a refresh, a new search, all the same.

One promise holds this together: **the number on the badge is the number the cutoff uses.** Nothing under the line appears above the fold, and the list always reads in descending order of the figure you can see. That is why picking a line with no tags on it, a bare "Vigilance, trample, haste", drops the concepts half entirely rather than scoring it zero: a perfect textual match would otherwise badge 50% while the gate let it through on 100. Bands never leapfrog each other either, which is what keeps the sorts meaningful down there, since sorting the whole tail by price returns the cheapest 0% match in the database.

Filters run inside the nearest neighbor query itself, so a narrow search digs deeper into the rankings instead of thinning an already-fetched list. Sorting happens after: filter by relevance, sort by whatever you like, ties broken by match score. Price never mixes into the similarity percent, so the number always means one thing.

Name search runs on the pg_trgm extension: exact match, then prefix, then substring, then trigram similarity, so "lightnig bolt" still finds Lightning Bolt. The autocomplete dropdown works the same way.

### The feedback loop

The results page can report three things: a card that shouldn't be in the results (the flag under each card, which asks why in the user's own words, since nobody is expected to name a better card off the top of their head), a card that should have been there but isn't (the link in the results heading, which asks for the card's name), and a tag on the wrong line (under the tag picker, once a line is picked). Missing card reports get diagnosed before anything is stored: when a filter is hiding the card, the reporter is told which one on the spot and the report never enters the queue, because that isn't the model's fault. Real gaps land in the `feedback` table with the reason, the scores and the model version at report time.

Tag reports never ask which direction the complaint runs. A tag is either on the picked line right now or it is not, and that decides whether the user means "you set this aside and the line IS about it" or "you kept this and the line is NOT". The answer is already in the database, and the direction is recorded at report time rather than looked up later, because the attribution gets rebuilt nightly and the report has to still make sense afterwards.

A review page at `/admin?key=...` (it exists only when `ADMIN_KEY` is set on the web service) shows pending reports with the cards side by side, accept and reject buttons, and exports accepted ones in the format of whichever eval file they belong to: misplaced reports become triplet negatives with the match left to fill in by hand, missing reports become pair entries, and tag reports become labelled lines for the attribution exam, which tests the one thing the others cannot, whether a tag landed on the right line rather than on the right card. Those files are the hand checked test sets the next model is graded against, so user complaints literally turn into the exam.

## Tech stack

- **Backend:** Python / Flask
- **Database:** Postgres + pgvector on Railway
- **Frontend:** Jinja templates + vanilla JavaScript
- **Similarity:** sentence-transformers (a fine tuned EmbeddingGemma), embedded at ingest time only
- **Card data:** Scryfall bulk data (Oracle Cards), refreshed daily by GitHub Actions

## A typical search

1. Type a card name. The card appears with its image and full rules text.
2. Below it, the 20 closest cards, each with the line that matched, its price and how close the match was.
3. Only care about one ability? Click that line and the search reruns on just it, on both halves of the score. Click more lines to combine them.
4. Narrow with the filter bar, then sort by price when hunting a cheaper version of something. The arrow next to each price says which way it moves against the card you searched.
5. Load 20 more digs deeper into the rankings. Clicking any card opens it on Scryfall.
