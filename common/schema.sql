--the whole database in one file. everything is IF NOT EXISTS so its safe to
--run over and over. ingest/update.py runs this at the start of every run,
--which means a brand new empty database sets itself up on the first run

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

--one row per unique card. scryfall's oracle_id stays the same across every
--printing of a card, so its the perfect primary key. text_hash is how the
--updater spots cards whose text changed without comparing whole strings
CREATE TABLE IF NOT EXISTS cards (
    oracle_id    uuid PRIMARY KEY,
    name         text NOT NULL,
    mana_cost    text,
    type_line    text,
    oracle_text  text,
    image        text,
    scryfall_uri text,
    text_hash    text NOT NULL,
    updated_at   timestamptz DEFAULT now(),
    --the filter columns. the ingest refreshes these on every run even when
    --the rules text didnt change, since prices move every day
    color_identity  text NOT NULL DEFAULT '',
    price_usd       numeric,  --the cheapest paper printing in any finish, not scryfall's preferred printing
    price_eur       numeric,  --the cheapest paper printing in euros, the currency toggle's other half
    cmc             numeric NOT NULL DEFAULT 0,  --mana value. numeric because scryfall says so, in practice whole numbers
    game_changer    boolean NOT NULL DEFAULT false,
    legal_commander boolean NOT NULL DEFAULT true,
    layout          text NOT NULL DEFAULT 'normal',
    image_back      text NOT NULL DEFAULT ''
);

--databases created before the filter columns existed pick them up here.
--fresh ones already have them from the CREATE TABLE above, and IF NOT
--EXISTS makes rerunning free either way
ALTER TABLE cards ADD COLUMN IF NOT EXISTS color_identity text NOT NULL DEFAULT '';
ALTER TABLE cards ADD COLUMN IF NOT EXISTS price_usd numeric;
ALTER TABLE cards ADD COLUMN IF NOT EXISTS price_eur numeric;
ALTER TABLE cards ADD COLUMN IF NOT EXISTS cmc numeric NOT NULL DEFAULT 0;
ALTER TABLE cards ADD COLUMN IF NOT EXISTS game_changer boolean NOT NULL DEFAULT false;
ALTER TABLE cards ADD COLUMN IF NOT EXISTS legal_commander boolean NOT NULL DEFAULT true;

--the /unique page. a card's uniqueness is its most isolated line: 1 minus
--the best match that line has anywhere else in the game. its judged per
--line on purpose, a card with Flying plus one ability nobody else has is
--unique in the "could define a deck" sense, even though the Flying line
--matches thousands of cards. unique_line remembers which line earned the
--score so the page can show it. both stay NULL for cards with no
--searchable lines, which quietly keeps them out of the unique deck
ALTER TABLE cards ADD COLUMN IF NOT EXISTS uniqueness real;
ALTER TABLE cards ADD COLUMN IF NOT EXISTS unique_line text;

--the concept counterpart: how alone a card is in tag space, 1 minus the
--best cosine any other card's tag vector manages. filled by ingest/tags.py
--so /unique can slide between rules-text-unique and concept-unique. stays
--NULL for untagged cards, unknown is not the same as unique
ALTER TABLE cards ADD COLUMN IF NOT EXISTS concept_uniqueness real;

--scryfall's edhrec popularity rank, 1 is the most played card in the
--format. powers the most/least played sorts. NULL means unranked, which
--reads as maximally obscure
ALTER TABLE cards ADD COLUMN IF NOT EXISTS edhrec_rank int;

--when the card first existed: the earliest released_at across every
--printing, tracked by the same default_cards scan that hunts prices.
--powers the newest sort. NULL sinks to the bottom of that sort
ALTER TABLE cards ADD COLUMN IF NOT EXISTS released_at date;

--edhrec's salt score: how much a card annoys people, from their annual salt
--survey, carried to us by mtgjson (scryfall does not have it). filled by
--ingest/salt.py.
--
--this is the only number in the database that is an opinion rather than a
--measurement, and that is the point of it, not a flaw. everything else here
--is derived from what a card does; salt is what players think of being on the
--other side of it, which no amount of rules text analysis can reach. so the
--votes are stored exactly as cast, protest votes included: filtering the ones
--that look "wrong" would be overriding the poll with our own taste, and then
--it would no longer be measuring what it says it measures.
--
--NULL means nobody voted, which is not the same as zero. roughly 8% of cards
--have no score, and they are overwhelmingly cards too new or too obscure to
--have annoyed anyone yet
ALTER TABLE cards ADD COLUMN IF NOT EXISTS salt real;

--how the card physically works, straight from scryfall: 'split' and battle
--type lines mean the picture is printed sideways and the site offers a
--rotate button, 'flip' means the bottom half reads upside down, and
--image_back holds the other face's picture when one exists so the card can
--be turned over on the page
ALTER TABLE cards ADD COLUMN IF NOT EXISTS layout text NOT NULL DEFAULT 'normal';
ALTER TABLE cards ADD COLUMN IF NOT EXISTS image_back text NOT NULL DEFAULT '';

--trigram index so the name searches (prefix, substring, fuzzy) stay quick
CREATE INDEX IF NOT EXISTS cards_name_trgm ON cards USING gin (name gin_trgm_ops);

--one row per line of rules text, with its embedding (768 numbers from my
--fine tuned embeddinggemma, normalized, so cosine distance works). databases
--still on the old 384 column get moved over by update.py when it notices
--the model changed.
--
--nn_sim is the line's nearest neighbor similarity: how close the closest
--line on any other card gets to this one. 1.0 means some other card has
--this exact ability, low means nothing else in the game does anything like
--it. update.py fills it in after the embeddings, its search turned inside
--out (search asks whats closest, this asks how far away even the closest
--thing is)
CREATE TABLE IF NOT EXISTS lines (
    id        bigserial PRIMARY KEY,
    oracle_id uuid NOT NULL REFERENCES cards(oracle_id) ON DELETE CASCADE,
    line_text text NOT NULL,
    embedding vector(768) NOT NULL,
    nn_sim    real,
    face      smallint NOT NULL DEFAULT 0
);

--the second bench, for trying a new model without losing the old one. swapping
--EMBED_MODEL overwrites every vector in place, which is a one way door: the old
--numbers are gone and only a rerun of the old model brings them back. filling a
--second column instead leaves the live one untouched, so the switch is
--EMBED_COLUMN on the web service and reverting is unsetting it.
--
--nullable, unlike embedding: rows exist long before anything fills it.
--ingest/backfill_embeddings.py is what fills it and the daily update does not
--maintain it, so it goes stale during a trial, which is fine for one.
--
--the line below stays commented. a trial ends in a rename swap (embedding ->
--embedding_v1, embedding_v2 -> embedding), and creating the column here would
--add an empty one back on the next ingest. backfill_embeddings.py adds it
--itself when a new trial starts.
--ALTER TABLE lines ADD COLUMN IF NOT EXISTS embedding_v2 vector(768);

--the previous model's vectors, the rollback for the current one: reverting is
--renaming the two columns back. drop it once the live model has been up long
--enough to trust and take back ~330mb with it
ALTER TABLE lines ADD COLUMN IF NOT EXISTS embedding_v1 vector(768);

ALTER TABLE lines ADD COLUMN IF NOT EXISTS nn_sim real;

--which face printed the line, 0 front / 1 back. when the winning match
--lives on a card's back face the results page shows that side first, so
--the line under the picture is on the picture (the ulvenwald lesson: the
--back face really does print "{T}: Add {C}{C}.", the display just hid it)
ALTER TABLE lines ADD COLUMN IF NOT EXISTS face smallint NOT NULL DEFAULT 0;

--whole-card rows: one extra row per multi-line card holding its entire
--cleaned text, for the line-merging blind spot (two separate lines that
--together equal another card's compound line - shadrix vs gluntch). they
--are retrieval material for a future card-level scorer and stay out of
--everything line-shaped: uniqueness, line_stats, the per-line search and
--the training miner all filter on NOT whole
ALTER TABLE lines ADD COLUMN IF NOT EXISTS whole boolean NOT NULL DEFAULT false;

--lets us grab one card's lines instantly at search time
CREATE INDEX IF NOT EXISTS lines_oracle_id ON lines (oracle_id);

--approximate index for the search's nearest neighbor scans, ~20ms per line
--where the exact scan measured 200-250ms. the dense build parameters are
--load bearing: common lines put hundreds of identical embeddings in the
--graph, and the default m=16/ef_construction=64 build leaves those clusters
--badly connected (a 94% match at true rank 181 fell out of a top-400 scan).
--m=32/ef_construction=200 measured zero misses above 0.90 sim against the
--exact scan. partial on NOT whole to mirror the search's filter, so
--whole-card rows never enter the graph. scan settings live in web/db.py,
--uniqueness is unaffected, recompute_uniqueness does its math in numpy
CREATE INDEX IF NOT EXISTS lines_embedding_hnsw ON lines USING hnsw (embedding vector_cosine_ops) WITH (m = 32, ef_construction = 200) WHERE (NOT whole);

--the same index for the second bench, same parameters because the search
--behaves identically whichever column it reads. NOT created here: an hnsw
--index that exists while 60k rows are being filled makes the backfill crawl,
--and building it afterwards over the finished column is both faster and
--better connected. ingest/backfill_embeddings.py creates it when it is done,
--and drops it again if the trial is abandoned

--how many cards share each line, for the idf weighting ("Flying" is on
--thousands of cards so it barely counts, a wordy triggered ability is nearly
--unique so it counts full strength). keyed by exact text because that is what
--the search joins on, but counted per shape: update.py collapses each run of
--mana symbols to a placeholder first, so "Overload {4}{R}" and "Overload
--{2}{R}" share a bucket instead of each looking unique at full weight
CREATE TABLE IF NOT EXISTS line_stats (
    line_text text PRIMARY KEY,
    count     int NOT NULL
);

--little key/value table for bookkeeping: a row per pipeline, plus the two
--calibration maps:
--
--  scryfall_updated_at   the bulk file update.py processed last
--  tagger_updated_at     the same, for tags.py's oracle_tags file
--  mtgjson_version       the same, for decks.py
--  mtgjson_deck_fields   which per-deck columns decks.py filled, so ADDING one
--                        forces exactly one rebuild without waiting on mtgjson
--  mtgjson_salt_version  the same, for salt.py. its own key, because shared
--                        with decks.py, whichever ran second would see the
--                        version already recorded and skip itself forever
--  embed_model           which model made the vectors, so a swap rebuilds them
--  mech_calibration      raw cosine -> displayed percent, for each axis. they
--  concept_calibration   ride here so the site and the pipeline can never
--                        disagree about what a percent means, and so a model
--                        swap carries its new map along with its new vectors
--
--the first five are all the same idea: doing nothing costs nothing, because
--every pipeline asks this table whether it has already seen what it just
--downloaded
CREATE TABLE IF NOT EXISTS meta (
    key   text PRIMARY KEY,
    value text
);

--privacy-preserving visitor counting. the web app creates these too (railway
--only deploys web/), they live here so the ingest self-heals a fresh database
--like every other table. the design is the privacy-first standard: a per-day
--salt that is deleted once the day is over, so the stored tokens can never be
--turned back into an ip afterwards, and the raw ip is never written at all.
--nothing here touches the visitor's device, which is what keeps the site free
--of a cookie banner.
--
--visit_salt holds only the current day's salt (older rows are deleted as each
--day rolls over). visit_seen is that day's distinct visitor tokens, also
--cleared once the day is counted. visit_daily is all that survives: one
--integer per day, fully anonymous
CREATE TABLE IF NOT EXISTS visit_salt (
    day  date PRIMARY KEY,
    salt text NOT NULL
);

CREATE TABLE IF NOT EXISTS visit_seen (
    day   date NOT NULL,
    token text NOT NULL,
    PRIMARY KEY (day, token)
);

CREATE TABLE IF NOT EXISTS visit_daily (
    day     date PRIMARY KEY,
    uniques int NOT NULL
);

--axis 2 (conceptual similarity) groundwork: community tags from scryfall
--tagger, via the official oracle_tags bulk file. one row per card-tag link.
--ingest/tags.py rebuilds both tables from scratch whenever the bulk file
--changes, same philosophy as line_stats
CREATE TABLE IF NOT EXISTS card_tags (
    oracle_id uuid NOT NULL REFERENCES cards(oracle_id) ON DELETE CASCADE,
    tag       text NOT NULL,
    PRIMARY KEY (oracle_id, tag)
);

CREATE INDEX IF NOT EXISTS card_tags_tag ON card_tags (tag);

--tagger's tags form a tree (see tags.parents): a card tagged gives-nimble is
--implicitly gives-evasion too. those implied rows live here alongside the
--real ones with inherited = true, so the scoring queries read card_tags and
--get the whole concept without knowing the tree exists, while anything that
--needs what a human actually typed filters on NOT inherited. without this
--siblings score zero against each other (delney/tetsuko both give evasion
--and shared nothing), which was two thirds of the axis's linking signal
ALTER TABLE card_tags ADD COLUMN IF NOT EXISTS inherited boolean NOT NULL DEFAULT false;

--what this card-tag link is worth to the scorer: the tag's idf, halved when
--the row was inherited rather than typed by a human. rolling up undamped
--floods every pair with generic ancestors (removal, card-advantage) and the
--gap between a real match and a generic near-miss collapsed from .199 to
--.078, so the weights carry the damping and the queries just read it. both
--sides of a pair can weigh the same tag differently, which is why the
--numerator is sum(a.weight * b.weight) and not sum(idf * idf)
ALTER TABLE card_tags ADD COLUMN IF NOT EXISTS weight real NOT NULL DEFAULT 0;

--one row per tag that survived the trivia blocklist: its parents (tagger
--tags form a hierarchy, kept for rollup scoring later), how many of our
--cards carry it, the idf weight derived from that count (so broad tags like
--triggered-ability barely count), and the tagger description for tooltips
CREATE TABLE IF NOT EXISTS tags (
    tag         text PRIMARY KEY,
    parents     text[] NOT NULL DEFAULT '{}',
    card_count  int NOT NULL DEFAULT 0,
    idf         real NOT NULL DEFAULT 0,
    description text NOT NULL DEFAULT ''
);

ALTER TABLE tags ADD COLUMN IF NOT EXISTS idf real NOT NULL DEFAULT 0;

--derived at ingest, like line_stats: each card's idf-weighted tag vector
--length, so the concept query never recomputes 31k norms per search
CREATE TABLE IF NOT EXISTS card_tag_norms (
    oracle_id uuid PRIMARY KEY REFERENCES cards(oracle_id) ON DELETE CASCADE,
    norm      real NOT NULL
);

--preconstructed commander decks from mtgjson, the calibration set for deck
--originality. a deck's originality score means nothing on its own ("0.24" is
--not a sentence), it only reads against other decks, and precons are the one
--population where the comparison is fair: same size, same format, same budget
--tier, same design brief. so this is not a nice-to-have list, it is what lets
--a pasted decklist be told where it stands.
--
--mtgjson hands us identifiers.scryfallOracleId on every card, so this joins
--straight to cards with no name matching anywhere. ingest/decks.py rebuilds
--both tables whenever mtgjson publishes a new version, same philosophy as
--line_stats and the tag tables
CREATE TABLE IF NOT EXISTS decks (
    slug         text PRIMARY KEY,  --mtgjson's fileName, e.g. MindSeize_C13
    name         text NOT NULL,
    code         text NOT NULL DEFAULT '',  --the set the deck shipped in
    release_date date,
    type         text NOT NULL DEFAULT ''
);

--where the decklist was published, which mtgjson carries for every deck: 179
--of the 190 point at magic.wizards.com and the other 11 at mtg.wiki. for the
--older sets it is that deck's own page, for recent ones it is the set's
--announcement article carrying all four or five lists at once, so it is a
--provenance link rather than a deep link and the page should not promise more
ALTER TABLE decks ADD COLUMN IF NOT EXISTS source text NOT NULL DEFAULT '';

--no originality column on purpose. the score is derived from cards.uniqueness,
--which moves every time the embedding model changes, so a stored number would
--quietly rot into a lie about a model that no longer exists. 166 decks by ~100
--cards is 16k rows, small enough that the leaderboard aggregates on the fly and
--is always telling the truth about the CURRENT scores. this is the opposite
--call to card_tag_norms and it is the size of the table that makes it right
CREATE TABLE IF NOT EXISTS deck_cards (
    deck_slug    text NOT NULL REFERENCES decks(slug) ON DELETE CASCADE,
    oracle_id    uuid NOT NULL REFERENCES cards(oracle_id) ON DELETE CASCADE,
    count        int NOT NULL DEFAULT 1,
    is_commander boolean NOT NULL DEFAULT false,
    PRIMARY KEY (deck_slug, oracle_id)
);

CREATE INDEX IF NOT EXISTS deck_cards_oracle ON deck_cards (oracle_id);

--which tags each line is about, so picking one ability on the search page can
--narrow the concept axis to that ability instead of searching the whole
--card's tag vector. tagger tags cards, never lines, so this is inferred
--rather than given: a line's nearest neighbours across the corpus vote with
--their own cards' tags, and a tag lands on the line whose neighbourhood
--carries it far more often than the game at large does (lift over base rate).
--only the tags a human typed get attributed, the inherited ancestors follow
--from the tree at query time exactly as they do for a whole card.
--
--card_level marks a tag no single line explains: invitational-card, or anything
--describing the card rather than one of its abilities. every row is false,
--because ingest/attribute.py drops such tags rather than riding them on every
--line. a tag about no ability should be absent once an ability is picked, and a
--whole-card search never reads this table, so nothing is lost. the column is
--here for the day TODO.md's step two revisits that.
--
--filled by ingest/attribute.py, rebuilt whenever lines or tags change
CREATE TABLE IF NOT EXISTS line_tags (
    line_id    bigint NOT NULL REFERENCES lines(id) ON DELETE CASCADE,
    tag        text NOT NULL,
    lift       real NOT NULL,
    card_level boolean NOT NULL DEFAULT false,
    PRIMARY KEY (line_id, tag)
);

CREATE INDEX IF NOT EXISTS line_tags_line ON line_tags (line_id);

--user reports from the search page, the raw material for the next round of
--the eval files. kind 'missing' means "this good card should have been in
--the results" and carries expected_id (a future pairs.md entry), kind
--'misplaced' means "this bad card shouldnt be here" and carries got_id plus
--the user's reason in their own words (a future triplets.md negative).
--names are snapshotted alongside the ids on purpose: cards can vanish from
--the cards table between the report and the review, and a report thats lost
--its cards should still read. the percents and embed_model pin down what
--the site actually said at report time, since both move whenever the model
--changes. no foreign keys, same reason
CREATE TABLE IF NOT EXISTS feedback (
    id            bigserial PRIMARY KEY,
    kind          text NOT NULL,
    anchor_id     uuid NOT NULL,
    anchor_name   text NOT NULL,
    expected_id   uuid,
    expected_name text,
    got_id        uuid,
    got_name      text,
    expected_pct  int,
    got_pct       int,
    reason        text NOT NULL DEFAULT '',
    picked_lines  text NOT NULL DEFAULT '',
    filters       text NOT NULL DEFAULT '',
    embed_model   text NOT NULL DEFAULT '',
    ip            text NOT NULL DEFAULT '',
    status        text NOT NULL DEFAULT 'pending',
    created_at    timestamptz DEFAULT now()
);

--a third kind of report, 'tag': the line picker set a tag aside that the
--picked line is about, or kept one it is not about. those are complaints about
--ingest/attribute.py rather than about the model's ranking, and they are the
--only feedback that can grow finetune/attribution_eval.py, which has three
--hand labelled cards and is the one exam testing which line a tag lands on.
--the tag slug goes here. which direction the complaint runs is read off the
--attribution at review time rather than trusted from the form, so a report
--stays readable even if the attribution is rebuilt before anyone looks at it
ALTER TABLE feedback ADD COLUMN IF NOT EXISTS tag text NOT NULL DEFAULT '';

--feedback.ip holds the day's one-way token, never an address. /privacy says
--plainly that an ip address is never stored, so any row still carrying a real
--one has to go or the page is not telling the truth about what is on disk.
--
--length is what tells them apart with no ambiguity: a token is a sha256 hex
--digest, exactly 64 characters, and no ip address of either family is that
--long. the rate limit only ever looks an hour back so nothing is lost by
--clearing them, and matching on length rather than a date means this stays
--correct however long it sits here.
--
--idempotent like everything else in this file: after the first run it matches
--no rows. the web app runs the same statement at startup (railway only deploys
--web/) so it lands on the next deploy rather than waiting for an ingest
UPDATE feedback SET ip = '' WHERE ip <> '' AND length(ip) <> 64;
