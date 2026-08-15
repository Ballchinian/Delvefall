--the whole database in one file. everything is IF NOT EXISTS, and update.py runs
--it at the start of every run, so a brand new database sets itself up

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

--oracle_id is stable across every printing of a card, which is what makes it the
--key. text_hash is how the updater spots changed text without comparing strings
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
    --refreshed on every ingest even when the rules text didnt change, prices
    --moving every day
    color_identity  text NOT NULL DEFAULT '',
    price_usd       numeric,  --the cheapest paper printing in any finish, not scryfall's preferred printing
    price_eur       numeric,  --the cheapest paper printing in euros, the currency toggle's other half
    cmc             numeric NOT NULL DEFAULT 0,  --mana value. numeric because scryfall says so, in practice whole numbers
    game_changer    boolean NOT NULL DEFAULT false,
    legal_commander boolean NOT NULL DEFAULT true,
    layout          text NOT NULL DEFAULT 'normal',
    image_back      text NOT NULL DEFAULT ''
);

--databases predating the filter columns pick them up here
ALTER TABLE cards ADD COLUMN IF NOT EXISTS color_identity text NOT NULL DEFAULT '';
ALTER TABLE cards ADD COLUMN IF NOT EXISTS price_usd numeric;
ALTER TABLE cards ADD COLUMN IF NOT EXISTS price_eur numeric;
ALTER TABLE cards ADD COLUMN IF NOT EXISTS cmc numeric NOT NULL DEFAULT 0;
ALTER TABLE cards ADD COLUMN IF NOT EXISTS game_changer boolean NOT NULL DEFAULT false;
ALTER TABLE cards ADD COLUMN IF NOT EXISTS legal_commander boolean NOT NULL DEFAULT true;

--a card's MOST ISOLATED LINE: 1 minus the best match that line has anywhere
--else. per line rather than per card on purpose, so Flying plus one ability
--nobody else has still counts as unique. NULL for cards with no searchable
--lines, which keeps them off /unique
ALTER TABLE cards ADD COLUMN IF NOT EXISTS uniqueness real;
ALTER TABLE cards ADD COLUMN IF NOT EXISTS unique_line text;

--the same in tag space, 1 minus the best cosine any other card's tag vector
--manages. NULL for untagged cards: unknown is not the same as unique
ALTER TABLE cards ADD COLUMN IF NOT EXISTS concept_uniqueness real;

--scryfall's edhrec rank, 1 being the most played. NULL is unranked, which the
--sorts read as maximally obscure
ALTER TABLE cards ADD COLUMN IF NOT EXISTS edhrec_rank int;

--the EARLIEST released_at across every printing, so it says when the card first
--existed rather than when this printing did. NULL sinks in the newest sort
ALTER TABLE cards ADD COLUMN IF NOT EXISTS released_at date;

--edhrec's annual salt survey, carried by mtgjson (scryfall does not have it).
--
--the only number here that is an OPINION rather than a measurement, which is
--the point of it. the votes are stored exactly as cast, protest votes included:
--dropping the ones that look wrong would override the poll with our own taste,
--and it would stop measuring what it says it measures.
--
--NULL is nobody voted, not zero. ~8% of cards, overwhelmingly ones too new or
--obscure to have annoyed anyone yet
ALTER TABLE cards ADD COLUMN IF NOT EXISTS salt real;

--'split' and battle type lines print the picture sideways and get a rotate
--button, 'flip' means the bottom half reads upside down
ALTER TABLE cards ADD COLUMN IF NOT EXISTS layout text NOT NULL DEFAULT 'normal';
ALTER TABLE cards ADD COLUMN IF NOT EXISTS image_back text NOT NULL DEFAULT '';

--who can lead a deck, which "legendary creature" has not answered since 2025:
--a legendary Vehicle or Spacecraft with a PRINTED POWER can, and so can the
--planeswalkers whose text says so. computed by common/cards.can_command from
--scryfall's own fields, because the printed power is not in this table and the
--type line alone cannot tell The Eternity Elevator from the seven spacecraft
--that are commanders.
--
--DEFAULT false is safe to land ahead of the ingest that fills it: every query
--reading this ORs it with the old legendary-creature test, so an unfilled
--column behaves exactly as the site did before the column existed
ALTER TABLE cards ADD COLUMN IF NOT EXISTS can_command boolean NOT NULL DEFAULT false;

--when the RULES TEXT last changed, which is the only honest lastmod the sitemap
--has: updated_at moves on every run because prices do. NULL is "never seen to
--change", and those urls emit no lastmod at all rather than an invented one.
--update.py sets it off the stored text_hash, so it fills in as cards are errata'd
ALTER TABLE cards ADD COLUMN IF NOT EXISTS text_changed_at timestamptz;

--trigram index so the name searches (prefix, substring, fuzzy) stay quick
CREATE INDEX IF NOT EXISTS cards_name_trgm ON cards USING gin (name gin_trgm_ops);

--one row per line of rules text. the embedding is 768 numbers from the fine
--tuned embeddinggemma, NORMALIZED, so cosine distance works.
--
--nn_sim is how close the closest line on any OTHER card gets to this one: 1.0
--means somebody printed this exact ability, low means nothing in the game does
--anything like it. update.py fills it after the embeddings
CREATE TABLE IF NOT EXISTS lines (
    id        bigserial PRIMARY KEY,
    oracle_id uuid NOT NULL REFERENCES cards(oracle_id) ON DELETE CASCADE,
    line_text text NOT NULL,
    embedding vector(768) NOT NULL,
    nn_sim    real,
    face      smallint NOT NULL DEFAULT 0
);

--the second bench, for trying a model without losing the old one. swapping
--EMBED_MODEL overwrites every vector in place, a one way door: only a rerun of
--the old model brings the numbers back. a second column leaves the live one
--alone, so the switch is EMBED_COLUMN on the web service and reverting is
--unsetting it. the daily update does not maintain it, so it goes stale during a
--trial, which is fine for one.
--
--the line below STAYS COMMENTED. a trial ends in a rename swap (embedding ->
--embedding_v1, embedding_v2 -> embedding), so creating the column here would add
--an empty one back on the next ingest. backfill_embeddings.py adds it itself.
--ALTER TABLE lines ADD COLUMN IF NOT EXISTS embedding_v2 vector(768);

--the previous model's vectors: reverting is renaming the two columns back. drop
--it once the live model is trusted and take back ~330mb with it
ALTER TABLE lines ADD COLUMN IF NOT EXISTS embedding_v1 vector(768);

ALTER TABLE lines ADD COLUMN IF NOT EXISTS nn_sim real;

--0 front / 1 back, so a match on the back face shows that side and the line
--under the picture is on the picture (the ulvenwald lesson: the back really does
--print "{T}: Add {C}{C}.", the display just hid it)
ALTER TABLE lines ADD COLUMN IF NOT EXISTS face smallint NOT NULL DEFAULT 0;

--one extra row per multi-line card holding its whole cleaned text, for the
--line-merging blind spot (two lines that together equal another card's compound
--line, shadrix vs gluntch). retrieval material for a future card-level scorer,
--and OUT of everything line-shaped: uniqueness, line_stats, the per-line search
--and the training miner all filter on NOT whole
ALTER TABLE lines ADD COLUMN IF NOT EXISTS whole boolean NOT NULL DEFAULT false;

CREATE INDEX IF NOT EXISTS lines_oracle_id ON lines (oracle_id);

--~20ms per line where the exact scan measured 200-250ms. the dense build
--parameters are load bearing: common lines put hundreds of identical embeddings
--in the graph and the default m=16/ef_construction=64 leaves those clusters
--badly connected, dropping a 94% match at true rank 181 out of a top-400 scan.
--m=32/ef_construction=200 measured zero misses above 0.90 sim. partial on NOT
--whole to mirror the search's filter. scan settings live in web/db.py, and
--uniqueness is unaffected, recompute_uniqueness doing its math in numpy
CREATE INDEX IF NOT EXISTS lines_embedding_hnsw ON lines USING hnsw (embedding vector_cosine_ops) WITH (m = 32, ef_construction = 200) WHERE (NOT whole);

--the second bench's index is NOT created here: an hnsw index existing while 60k
--rows are filled makes the backfill crawl, and building it afterwards is faster
--and better connected. ingest/backfill_embeddings.py creates it when it is done
--and drops it again if the trial is abandoned

--how many cards share each line, for the idf weighting. keyed by exact text
--because that is what the search joins on, but counted PER SHAPE: update.py
--collapses each run of mana symbols to a placeholder first, so "Overload {4}{R}"
--and "Overload {2}{R}" share a bucket instead of each looking unique
CREATE TABLE IF NOT EXISTS line_stats (
    line_text text PRIMARY KEY,
    count     int NOT NULL
);

--bookkeeping: a row per pipeline, plus the two calibration maps. every pipeline
--asks this table whether it has already seen what it just downloaded, so doing
--nothing costs nothing:
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
CREATE TABLE IF NOT EXISTS meta (
    key   text PRIMARY KEY,
    value text
);

--visitor counting. the web app creates these too (railway only deploys web/),
--they are here so the ingest self-heals a fresh database like every other table.
--
--the salt is deleted once its day is over, which is what makes the stored tokens
--permanently unresolvable; the raw ip is never written at all. visit_seen is
--cleared with it, and visit_daily is all that survives: two integers per day
CREATE TABLE IF NOT EXISTS visit_salt (
    day  date PRIMARY KEY,
    salt text NOT NULL
);

CREATE TABLE IF NOT EXISTS visit_seen (
    day   date NOT NULL,
    token text NOT NULL,
    bot   boolean NOT NULL DEFAULT false,
    PRIMARY KEY (day, token)
);

--uniques counts people and bots counts the rest, split on the flag above. rows
--predating the column take the default, so their days read as all human
CREATE TABLE IF NOT EXISTS visit_daily (
    day     date PRIMARY KEY,
    uniques int NOT NULL,
    bots    int NOT NULL DEFAULT 0
);

--community tags from scryfall tagger, via the oracle_tags bulk file.
--ingest/tags.py rebuilds both tables from scratch whenever that file changes
CREATE TABLE IF NOT EXISTS card_tags (
    oracle_id uuid NOT NULL REFERENCES cards(oracle_id) ON DELETE CASCADE,
    tag       text NOT NULL,
    PRIMARY KEY (oracle_id, tag)
);

CREATE INDEX IF NOT EXISTS card_tags_tag ON card_tags (tag);

--tagger's tags form a tree (tags.parents): gives-nimble implies gives-evasion.
--the implied rows live here beside the typed ones, so scoring queries read
--card_tags and get the whole concept, while anything needing what a human
--actually typed filters on NOT inherited. without it siblings score zero against
--each other (delney/tetsuko both give evasion, shared nothing), which was two
--thirds of the axis's linking signal
ALTER TABLE card_tags ADD COLUMN IF NOT EXISTS inherited boolean NOT NULL DEFAULT false;

--the tag's idf, HALVED when inherited rather than typed. rolling up undamped
--floods every pair with generic ancestors (removal, card-advantage) and the gap
--between a real match and a generic near-miss collapsed from .199 to .078.
--
--both sides of a pair can weigh the same tag differently, which is why the
--numerator is sum(a.weight * b.weight) and not sum(idf * idf)
ALTER TABLE card_tags ADD COLUMN IF NOT EXISTS weight real NOT NULL DEFAULT 0;

--one row per tag that survived the trivia blocklist. idf is derived from
--card_count, so broad tags like triggered-ability barely count
CREATE TABLE IF NOT EXISTS tags (
    tag         text PRIMARY KEY,
    parents     text[] NOT NULL DEFAULT '{}',
    card_count  int NOT NULL DEFAULT 0,
    idf         real NOT NULL DEFAULT 0,
    description text NOT NULL DEFAULT ''
);

ALTER TABLE tags ADD COLUMN IF NOT EXISTS idf real NOT NULL DEFAULT 0;

--each card's tag vector length, baked so the concept query never recomputes 31k
--norms per search
CREATE TABLE IF NOT EXISTS card_tag_norms (
    oracle_id uuid PRIMARY KEY REFERENCES cards(oracle_id) ON DELETE CASCADE,
    norm      real NOT NULL
);

--precons from mtgjson, the calibration set for deck originality: "0.24" is not a
--sentence on its own, and precons are the one population where the comparison is
--fair (same size, format, budget tier, design brief). this is what lets a pasted
--decklist be told where it stands.
--
--mtgjson carries identifiers.scryfallOracleId on every card, so this joins
--straight to cards with NO NAME MATCHING anywhere. ingest/decks.py rebuilds both
--tables whenever mtgjson publishes a new version
CREATE TABLE IF NOT EXISTS decks (
    slug         text PRIMARY KEY,  --mtgjson's fileName, e.g. MindSeize_C13
    name         text NOT NULL,
    code         text NOT NULL DEFAULT '',  --the set the deck shipped in
    release_date date,
    type         text NOT NULL DEFAULT ''
);

--where the decklist was published (179 of the 190 at magic.wizards.com, 11 at
--mtg.wiki). for recent sets it is the announcement article carrying all four or
--five lists at once, so it is a PROVENANCE link rather than a deep one and the
--page should not promise more
ALTER TABLE decks ADD COLUMN IF NOT EXISTS source text NOT NULL DEFAULT '';

--no originality column ON PURPOSE. the score derives from cards.uniqueness,
--which moves whenever the embedding model changes, so a stored number would rot
--into a lie about a model that no longer exists. 166 decks by ~100 cards is 16k
--rows, small enough to aggregate on the fly. the opposite call to
--card_tag_norms, and it is the size of the table that makes it right
CREATE TABLE IF NOT EXISTS deck_cards (
    deck_slug    text NOT NULL REFERENCES decks(slug) ON DELETE CASCADE,
    oracle_id    uuid NOT NULL REFERENCES cards(oracle_id) ON DELETE CASCADE,
    count        int NOT NULL DEFAULT 1,
    is_commander boolean NOT NULL DEFAULT false,
    PRIMARY KEY (deck_slug, oracle_id)
);

CREATE INDEX IF NOT EXISTS deck_cards_oracle ON deck_cards (oracle_id);

--which tags each line is about, so picking one ability narrows the concept axis
--to that ability. tagger tags CARDS, never lines, so this is inferred: a line's
--nearest neighbours vote with their own cards' tags, and a tag lands where its
--neighbourhood carries it far more often than the game at large does (lift over
--base rate). only typed tags are attributed, the inherited ancestors following
--from the tree at query time as they do for a whole card.
--
--card_level would mark a tag no single line explains (invitational-card). every
--row is false: attribute.py drops those rather than riding them on every line,
--and a whole-card search never reads this table, so nothing is lost. the column
--is here for the day TODO.md's step two revisits it
CREATE TABLE IF NOT EXISTS line_tags (
    line_id    bigint NOT NULL REFERENCES lines(id) ON DELETE CASCADE,
    tag        text NOT NULL,
    lift       real NOT NULL,
    card_level boolean NOT NULL DEFAULT false,
    PRIMARY KEY (line_id, tag)
);

CREATE INDEX IF NOT EXISTS line_tags_line ON line_tags (line_id);

--user reports from the search page, raw material for the next round of eval
--files. 'missing' carries expected_id (a future exam_pairs.md entry), 'misplaced'
--carries got_id plus the reason in the user's own words (a future bakeoff_lines.md
--negative).
--
--names are snapshotted beside the ids and there are NO FOREIGN KEYS, both on
--purpose: cards can vanish between the report and the review, and a report that
--lost its cards should still read. the percents and embed_model pin down what
--the site said at the time, since both move whenever the model changes
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

--a third kind of report, 'tag': the picker set aside a tag the line is about, or
--kept one it is not. a complaint about ingest/attribute.py rather than the
--model's ranking, and the only feedback that can grow
--finetune/attribution_eval.py, which has three hand labelled cards.
--
--which DIRECTION the complaint runs is read off the attribution at review time
--rather than trusted from the form, so a report stays readable even if the
--attribution is rebuilt before anyone looks at it
ALTER TABLE feedback ADD COLUMN IF NOT EXISTS tag text NOT NULL DEFAULT '';

--feedback.ip holds the day's one-way token, never an address. /privacy says
--plainly that an ip is never stored, so a row carrying a real one has to go.
--
--LENGTH is the unambiguous discriminator: a token is a sha256 hex digest,
--exactly 64 characters, and no ip of either family is that long. matching on
--that rather than a date keeps this correct however long it sits here, and the
--rate limit only looks an hour back so nothing is lost by clearing them.
--
--the web app runs the same statement at startup (railway only deploys web/) so
--it lands on the next deploy rather than waiting for an ingest
UPDATE feedback SET ip = '' WHERE ip <> '' AND length(ip) <> 64;
