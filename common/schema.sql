--the whole database in one file. everything is IF NOT EXISTS, and update.py runs
--it at the start of every run, so a brand new database sets itself up

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

--every column added after its table was first made goes through this, because
--ADD COLUMN IF NOT EXISTS takes ACCESS EXCLUSIVE even when the column is there.
--the whole file is one transaction, so the first of those on cards waited for
--any search reading lines while every card page waited for it. asking the
--catalog first takes no lock a reader holds. pg_temp, so it lasts as long as the
--connection and is never part of the schema
CREATE OR REPLACE FUNCTION pg_temp.add_column(tab text, col text, decl text) RETURNS void
LANGUAGE plpgsql AS $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_attribute
                   WHERE attrelid = to_regclass(tab) AND attname = col AND NOT attisdropped) THEN
        EXECUTE format('ALTER TABLE %I ADD COLUMN IF NOT EXISTS %I ', tab, col) || decl;
    END IF;
END $$;

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
SELECT pg_temp.add_column('cards', 'color_identity', $$text NOT NULL DEFAULT ''$$);
SELECT pg_temp.add_column('cards', 'price_usd', $$numeric$$);
SELECT pg_temp.add_column('cards', 'price_eur', $$numeric$$);
SELECT pg_temp.add_column('cards', 'cmc', $$numeric NOT NULL DEFAULT 0$$);
SELECT pg_temp.add_column('cards', 'game_changer', $$boolean NOT NULL DEFAULT false$$);
SELECT pg_temp.add_column('cards', 'legal_commander', $$boolean NOT NULL DEFAULT true$$);

--a card's MOST ISOLATED LINE: 1 minus the best match that line has anywhere
--else. per line rather than per card on purpose, so Flying plus one ability
--nobody else has still counts as unique. NULL for cards with no searchable
--lines, which keeps them off /unique
SELECT pg_temp.add_column('cards', 'uniqueness', $$real$$);
SELECT pg_temp.add_column('cards', 'unique_line', $$text$$);

--the same in tag space, 1 minus the best cosine any other card's tag vector
--manages. NULL for untagged cards: unknown is not the same as unique
SELECT pg_temp.add_column('cards', 'concept_uniqueness', $$real$$);

--scryfall's edhrec rank, 1 being the most played. NULL is unranked, which the
--sorts read as maximally obscure
SELECT pg_temp.add_column('cards', 'edhrec_rank', $$int$$);

--the EARLIEST released_at across every printing, so it says when the card first
--existed rather than when this printing did. NULL sinks in the newest sort
SELECT pg_temp.add_column('cards', 'released_at', $$date$$);

--edhrec's annual salt survey, carried by mtgjson (scryfall does not have it).
--
--the only number here that is an OPINION rather than a measurement, which is
--the point of it. the votes are stored exactly as cast, protest votes included:
--dropping the ones that look wrong would override the poll with our own taste,
--and it would stop measuring what it says it measures.
--
--NULL is nobody voted, not zero. ~8% of cards, overwhelmingly ones too new or
--obscure to have annoyed anyone yet
SELECT pg_temp.add_column('cards', 'salt', $$real$$);

--'split' and battle type lines print the picture sideways and get a rotate
--button, 'flip' means the bottom half reads upside down
SELECT pg_temp.add_column('cards', 'layout', $$text NOT NULL DEFAULT 'normal'$$);
SELECT pg_temp.add_column('cards', 'image_back', $$text NOT NULL DEFAULT ''$$);

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
SELECT pg_temp.add_column('cards', 'can_command', $$boolean NOT NULL DEFAULT false$$);

--when the RULES TEXT last changed, which is the only honest lastmod the sitemap
--has: updated_at moves on every run because prices do. NULL is "never seen to
--change", and those urls emit no lastmod at all rather than an invented one.
--update.py sets it off the stored text_hash, so it fills in as cards are errata'd
SELECT pg_temp.add_column('cards', 'text_changed_at', $$timestamptz$$);

--trigram index so the name searches (prefix, substring, fuzzy) stay quick
CREATE INDEX IF NOT EXISTS cards_name_trgm ON cards USING gin (name gin_trgm_ops);

--one row per line of rules text. the embedding is 768 numbers from the fine
--tuned embeddinggemma, NORMALIZED, so cosine distance works.
--
--halfvec, 2 bytes a number. at 1,544 bytes the vector fits inside the row,
--where a 3,080 byte vector sat out of line in toast. measured against the full
--precision vectors: 3 of 7,935 search percents move a point and /unique's top
--100 holds its order. the rounding leaves a vector up to 1.2e-4 off length 1,
--which pgvector's <=> absorbs and a numpy dot product does not, so numpy reads
--them through common/vectors.py's unit_rows
--
--nn_sim is how close the closest line on any OTHER card gets to this one: 1.0
--means somebody printed this exact ability, low means nothing in the game does
--anything like it. update.py fills it after the embeddings
CREATE TABLE IF NOT EXISTS lines (
    id        bigserial PRIMARY KEY,
    oracle_id uuid NOT NULL REFERENCES cards(oracle_id) ON DELETE CASCADE,
    line_text text NOT NULL,
    embedding halfvec(768) NOT NULL,
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
--ALTER TABLE lines ADD COLUMN IF NOT EXISTS embedding_v2 halfvec(768);

--embedding_v1 was here and is GONE as of 2026-08-15, column and hnsw index both.
--it held nothing: the model swap's TRUNCATE rebuilt every row and only ever
--writes `embedding`, so the column read 0 of 79,991 populated while its index
--cost 182mb to index an empty column. rolling back to the v1 model was already
--not a column rename by then, whatever the note here used to say. that model is
--BallchinianMan/mtg-tuned-embeddinggemma-300m on HF and the repo is tagged
--v1-rules-text at the last commit before the swap.
--
--DO NOT re-add the ALTER. this file runs at the top of every ingest, so a line
--here puts the empty column back every morning

SELECT pg_temp.add_column('lines', 'nn_sim', $$real$$);

--0 front / 1 back, so a match on the back face shows that side and the line
--under the picture is on the picture (the ulvenwald lesson: the back really does
--print "{T}: Add {C}{C}.", the display just hid it)
SELECT pg_temp.add_column('lines', 'face', $$smallint NOT NULL DEFAULT 0$$);

--one extra row per multi-line card holding its whole cleaned text, for the
--line-merging blind spot (two lines that together equal another card's compound
--line, shadrix vs gluntch). retrieval material for a future card-level scorer,
--and OUT of everything line-shaped: uniqueness, line_stats, the per-line search
--and the training miner all filter on NOT whole
SELECT pg_temp.add_column('lines', 'whole', $$boolean NOT NULL DEFAULT false$$);

CREATE INDEX IF NOT EXISTS lines_oracle_id ON lines (oracle_id);

--~20ms per line where the exact scan measured 200-250ms. the dense build
--parameters are load bearing: identical lines ("Flying" on 2,566 rows, "Enchant
--creature" on 904) link almost only to each other and trap the walk, so a
--search for "Enchant land" comes back as 400 rows of "Enchant creature" and no
--ef_search gets it out. over all 35,987 distinct texts, m=32/ef_construction=200
--left 55 to 259 of them missing their best match per build and
--m=64/ef_construction=400 none in two builds, at 108mb against 86mb and as fast
--as the float32 m=32 graph searched. the default m=16/ef_construction=64
--dropped a 94% match at true rank 181. partial on NOT whole to mirror the
--search's filter. scan settings live in web/db.py, and uniqueness is
--unaffected, recompute_uniqueness doing its math in numpy
--the operator class is read off the column rather than written out, because
--CREATE INDEX IF NOT EXISTS resolves it against the live type BEFORE it checks
--whether the name is taken: naming halfvec_cosine_ops here threw
--DatatypeMismatch on every ingest run against a database still holding
--vector(768), index present and correct or not, which is what stopped the daily
--update between the halfvec commit and the rebuild that converts the column.
--this way the file applies to the database either side of that rebuild, and
--update.py prints which side it found
DO $$
BEGIN
    EXECUTE format(
        'CREATE INDEX IF NOT EXISTS lines_embedding_hnsw ON lines USING hnsw (embedding %s_cosine_ops) '
        'WITH (m = 64, ef_construction = 400) WHERE (NOT whole)',
        (SELECT split_part(format_type(atttypid, atttypmod), '(', 1) FROM pg_attribute
         WHERE attrelid = 'lines'::regclass AND attname = 'embedding'));
END $$;

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
--  embed_sha256          the release sha256 of its weights, so a retrain under
--                        the same name is a swap too
--  tag_probe_model       the same pair for the weights tag_probe was trained
--  tag_probe_sha256      against, so /custom shows no chips once they differ
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
--cleared with it, and visit_daily is all that survives: one row of counts a day
CREATE TABLE IF NOT EXISTS visit_salt (
    day  date PRIMARY KEY,
    salt text NOT NULL
);

--the flags are what the token DID that day: loaded a page, fetched the site's
--font, typed or clicked, read a crawler's file, claimed a browser without a
--browser's headers. html is the gate, since a visitor that only fetched the
--share image is not one of the day's people
CREATE TABLE IF NOT EXISTS visit_seen (
    day   date NOT NULL,
    token text NOT NULL,
    bot   boolean NOT NULL DEFAULT false,
    html  boolean NOT NULL DEFAULT true,
    font  boolean NOT NULL DEFAULT false,
    act   boolean NOT NULL DEFAULT false,
    crawl boolean NOT NULL DEFAULT false,
    lies  boolean NOT NULL DEFAULT false,
    PRIMARY KEY (day, token)
);

--uniques counts every visitor that is not a declared bot, and the three that
--follow divide it: suspect did what automation does, acted did what a person
--does, rendered drew the page. what is left over is unproven. NULL in any of
--them is a day that ended before it was measured, which a 0 would hide
CREATE TABLE IF NOT EXISTS visit_daily (
    day        date PRIMARY KEY,
    uniques    int NOT NULL,
    bots       int NOT NULL DEFAULT 0,
    suspect_n  int,
    acted_n    int,
    rendered_n int
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
SELECT pg_temp.add_column('card_tags', 'inherited', $$boolean NOT NULL DEFAULT false$$);

--the tag's idf, HALVED when inherited rather than typed. rolling up undamped
--floods every pair with generic ancestors (removal, card-advantage) and the gap
--between a real match and a generic near-miss collapsed from .199 to .078.
--
--both sides of a pair can weigh the same tag differently, which is why the
--numerator is sum(a.weight * b.weight) and not sum(idf * idf)
SELECT pg_temp.add_column('card_tags', 'weight', $$real NOT NULL DEFAULT 0$$);

--one row per tag that survived the trivia blocklist. idf is derived from
--card_count, so broad tags like triggered-ability barely count
CREATE TABLE IF NOT EXISTS tags (
    tag         text PRIMARY KEY,
    parents     text[] NOT NULL DEFAULT '{}',
    card_count  int NOT NULL DEFAULT 0,
    idf         real NOT NULL DEFAULT 0,
    description text NOT NULL DEFAULT ''
);

SELECT pg_temp.add_column('tags', 'idf', $$real NOT NULL DEFAULT 0$$);

--each card's tag vector length. the scoring queries read card_tag_vecs below
--instead, so this is left for common/concept.py, which the finetune scripts run
--a pair at a time
CREATE TABLE IF NOT EXISTS card_tag_norms (
    oracle_id uuid PRIMARY KEY REFERENCES cards(oracle_id) ON DELETE CASCADE,
    norm      real NOT NULL
);

--which dimension each tag occupies in card_tag_vecs. APPEND ONLY: a dim is
--handed out once and never reused, not even after a tag is retired.
--
--it needs its own table because ingest/tags.py rebuilds `tags` from scratch
--whenever scryfall publishes, so a dim column there would be reassigned the day
--a tag disappears and every stored vector would quietly mean something else.
--nothing raises on that, which is why the guarantee is structural here rather
--than a rule someone has to remember
CREATE TABLE IF NOT EXISTS tag_dims (
    tag text PRIMARY KEY,
    dim int NOT NULL UNIQUE
);

--everything /custom needs to know about a tag, and the only table the site reads
--that no ingest step writes: tools/load_tag_probe.py fills it, because two of
--the three things in it are trained and reviewed in finetune/ rather than
--derived from scryfall.
--
--w and b are a linear probe, one per tag: sigmoid(w . v + b) is how likely a
--typed line is about that tag, the half of the chip score that reads the text
--directly rather than through its neighbours. tags too rare to have been taught
--one sit here with w NULL, so the neighbour vote can still name them.
--
--NOT columns on `tags`: ingest/tags.py rebuilds that table from scratch whenever
--scryfall publishes, which would throw the probe away every morning. the same
--reasoning tag_dims is a table of its own for.
--
--vector rather than halfvec: these are weights, not unit vectors, and there is
--no index on them to shrink. 1,933 rows is about 6mb.
--
--banned carries make_tagreview.md's card and junk verdicts, which are never
--chips: out-of-color-token was right 26% of the time, doom-blade 7%.
--
--types is unread, and tools/load_tag_probe.py leaves it at its default: /custom
--has no type filter. the column stays: dropping it locks a table /custom reads,
--and a web rollback to a version that still selects it would 500
CREATE TABLE IF NOT EXISTS tag_probe (
    tag    text PRIMARY KEY,
    w      vector(768),
    b      real,
    banned boolean NOT NULL DEFAULT false,
    types  jsonb NOT NULL DEFAULT '{}'
);

--the concept axis's candidate side: the same weights card_tags holds, laid out
--so pgvector computes sum(a.weight * b.weight) / (|a| * |b|) in one pass.
--
--that IS the cosine the axis was already computing, so the number does not move
--and concept_calibration is untouched. what moves is the cost: one anchor
--reaches 45,322 postings over 22,232 cards through card_tags and aggregates
--every one of them, 65-181ms. this answers the same question in 8-10ms.
--
--NO HNSW INDEX, and that is measured rather than skipped. the injection query
--cuts at concept_raw_gate(TIER_CUT), which only 9-212 cards clear against a
--LIMIT 300, so an ordered graph walk never fills its quota, never short
--circuits, and ran 32-45ms where the plain scan runs 29ms. an index here would
--cost speed AND exactness. what makes scanning all of it cheap is the width:
--31,392 rows at ~96 bytes is 4.4mb, against 42mb of card_tags and 49mb of cards.
--
--8192 is headroom over the 2,794 tags that exist, a sparsevec declaring its
--dimension and a new tag otherwise rewriting the column. tags.py reads that
--number back out of this declaration rather than keeping a second copy of it
CREATE TABLE IF NOT EXISTS card_tag_vecs (
    oracle_id uuid PRIMARY KEY REFERENCES cards(oracle_id) ON DELETE CASCADE,
    vec       sparsevec(8192) NOT NULL
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
SELECT pg_temp.add_column('decks', 'source', $$text NOT NULL DEFAULT ''$$);

--false only where the source url was SEEN to 404. wizards deleted its old
--card-set-archive section, so 16 of the links above lead nowhere.
--DEFAULT true, and it matters: a database the check has never run against shows
--every link, which is how the site behaved before the column existed. the check
--only ever takes a link away on proof
SELECT pg_temp.add_column('decks', 'source_ok', $$boolean NOT NULL DEFAULT true$$);

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
SELECT pg_temp.add_column('feedback', 'tag', $$text NOT NULL DEFAULT ''$$);

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
