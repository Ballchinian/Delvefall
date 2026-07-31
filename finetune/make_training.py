#builds the training set out of the site's own card lines. positives are pairs of
#real lines near-identical on real cards (numbers, riders, scope), negatives are
#real lines with one mechanism flipped (tap vs untap, hand vs battlefield,
#draw-then-discard order).
#
#anything in bakeoff_lines.py's triplets is EXCLUDED: the model must never train
#on its own exam.
#
#    python finetune/make_training.py
#reads DATABASE_URL or the repo .env, falling back to the scryfall bulk file.
#writes train_pairs.jsonl, train_negatives.jsonl and train_triplets.jsonl

import os
import re
import sys
import json
import random
import collections

#oracle text is full of characters the windows console cant print ({T}, the
#real minus sign in loyalty costs, bullets in modal spells)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from common.cards import HEADERS, keep_card, split_lines, bulk_uri, read_bulk

from bakeoff_lines import TRIPLETS
from common.cards import clean_line

random.seed(7)
OUT_DIR = os.path.dirname(os.path.abspath(__file__))
#the tag objective's jsonl files. the line objective's live in
#legacy/traindata, and dump() below routes them there
DATA_DIR = os.path.join(OUT_DIR, "traindata")


def load_lines_from_db(db_url):
    import psycopg
    conn = psycopg.connect(db_url)
    rows = conn.execute("SELECT DISTINCT line_text FROM lines WHERE NOT whole").fetchall()
    conn.close()
    return [r[0] for r in rows]


def load_lines_from_scryfall():
    import requests
    print("no DATABASE_URL found, downloading the scryfall bulk file instead...")
    bulk = None
    for item in requests.get("https://api.scryfall.com/bulk-data", headers=HEADERS, timeout=120).json()["data"]:
        if item["type"] == "oracle_cards":
            bulk = item
    #only the cleaned lines are kept, a fraction of what arrives
    path = os.path.join(OUT_DIR, "oracle-cards.jsonl.gz")
    with requests.get(bulk_uri(bulk), headers=HEADERS, timeout=300, stream=True) as r:
        r.raise_for_status()
        with open(path, "wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 1024):
                f.write(chunk)
    lines = set()
    for c in read_bulk(path):
        if keep_card(c):
            for line, face in split_lines(c):
                lines.add(line)
    os.remove(path)
    return sorted(lines)


def find_db_url():
    if os.environ.get("DATABASE_URL"):
        return os.environ["DATABASE_URL"]
    env_path = os.path.join(OUT_DIR, "..", ".env")
    if os.path.exists(env_path):
        for raw in open(env_path, encoding="utf-8"):
            raw = raw.strip()
            if raw.startswith("DATABASE_URL="):
                return raw.split("=", 1)[1].strip().strip('"').strip("'")
    return None


#---- positives: pairs of real lines that mean nearly the same thing ----

NUMBER_WORDS = r"(?:a|an|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|X|\d+)"


def number_key(line):
    #two lines that only differ in their numbers collapse to the same key
    return re.sub(r"\b" + NUMBER_WORDS + r"\b", "#", line)


SCOPE_WORDS = ["creature", "noncreature", "artifact", "enchantment", "instant", "sorcery",
               "basic", "legendary", "nonland", "nontoken", "nonbasic", "attacking", "blocking",
               "tapped", "white", "blue", "black", "red", "green", "colorless", "another"]

#subtype riders are forgivable the same way ("cast Dragon spells" is still "cast
#spells", exam_pairs.md should-match #3). the frequent types are enough, a pair only
#surviving when deleting the word lands on a real line
SUBTYPE_WORDS = ["Dragon", "Zombie", "Goblin", "Elf", "Human", "Angel", "Demon", "Vampire",
                 "Dinosaur", "Wizard", "Warrior", "Knight", "Soldier", "Spirit", "Elemental",
                 "Sliver", "Merfolk", "Beast", "Cat", "Bird", "Snake", "Wolf", "Faerie",
                 "Giant", "Dwarf", "Wall", "Aura", "Equipment", "Vehicle",
                 "Forest", "Island", "Swamp", "Mountain", "Plains"]


def mine_positives(lines):
    line_set = set(lines)
    pairs = []

    #lines that are identical once you blank out the numbers
    groups = {}
    for line in lines:
        groups.setdefault(number_key(line), []).append(line)
    for group in groups.values():
        if len(group) > 1:
            group = sorted(group)
            random.shuffle(group)
            #cap the pairs per group or "draw # cards" would flood the set
            for a, b in list(zip(group, group[1:]))[:3]:
                pairs.append((a, b, "number variant"))

    #rider variants: one line is the other plus an extra sentence on the end
    #(unsummon vs vapor snag)
    by_first_sentence = {}
    for line in lines:
        first = line.split(". ")[0] + "." if ". " in line else line
        by_first_sentence.setdefault(first, []).append(line)
    for first, group in by_first_sentence.items():
        if first in line_set:
            for line in group:
                if line != first:
                    pairs.append((first, line, "rider variant"))

    #scope variants: deleting one qualifier word lands on another real line
    #(counter target creature spell vs counter target spell)
    for line in lines:
        for word in SCOPE_WORDS:
            if " " + word + " " in line:
                shorter = line.replace(" " + word + " ", " ", 1)
                if shorter in line_set and shorter != line:
                    pairs.append((line, shorter, "scope variant"))

    #subtype riders, same trick with type words
    for line in lines:
        for word in SUBTYPE_WORDS:
            if " " + word + " " in line:
                shorter = line.replace(" " + word + " ", " ", 1)
                if shorter in line_set and shorter != line:
                    pairs.append((line, shorter, "subtype variant"))

    #the etb wrapper says WHEN, not what, so the same effect with and without
    #"When this creature enters, " in front is a pair (the earth-cult report)
    for line in lines:
        m = re.match(r"^When(?:ever)? this creature enters, (?:you may )?(.+)$", line)
        if m and len(m.group(1)) > 15:
            bare = m.group(1)[0].upper() + m.group(1)[1:]
            if bare in line_set:
                pairs.append((line, bare, "etb wrapper"))

    #hexproof and shroud differ in who they stop, not what they are (triplet 29,
    #boots vs greaves). SYNTHETIC positives, the same line with the word swapped
    for line in lines:
        low = line.lower()
        if "hexproof" in low and "shroud" not in low:
            pairs.append((line, re.sub(r"[Hh]exproof", "shroud", line), "keyword synonym"))
        elif "shroud" in low and "hexproof" not in low:
            pairs.append((line, re.sub(r"[Ss]hroud", "hexproof", line), "keyword synonym"))

    #quantity is the forgivable half of triplet 28 ("{T}: Add {C}." against
    #"{T}: Add {C}{C}."), COLOUR is the payload half, handled in the negatives
    groups = {}
    for line in lines:
        if "Add {" in line:
            groups.setdefault(re.sub(r"(\{[WUBRGC]\})(?:\1)+", r"\1", line), []).append(line)
    for group in groups.values():
        if len(group) > 1:
            group = sorted(group)
            random.shuffle(group)
            for a, b in list(zip(group, group[1:]))[:3]:
                pairs.append((a, b, "mana amount variant"))
    return pairs


#---- line <-> tag: the supervision tagger already did ----

#every class above needs a regex to guess what similar means. this one does not:
#a card whose whole text is one line, paired with the tags a human typed on it,
#is unambiguous supervision. 11,680 such cards carry 52,708 links.
#
#not every tag is learnable from text though. color-break is about the mana cost,
#vanity-card about the artist, wth-storyline-in-cards is set flavour, and no
#model reads "Destroy target permanent." and concludes "meme". this asks whether
#a tag is separable at all: held out, are its cards nearer the tag's centroid
#than cards without it? the ones that fail are the flavour and cost tags
LEARNABLE_AUC = 0.75
TAG_TEST_FRACTION = 0.15   #single-line cards held back to measure attribution

#one draw of that test is not a measurement: holding back a third of a tag's
#cards and sampling 800 negatives swings the answer by +/-0.066 between seeds at
#10 to 19 cards and +/-0.050 at 20 to 49, while 114 of the 706 tags sit within
#0.05 of the bar. on a sixth of the pool a single draw decides the verdict by
#seed rather than by tag, and averaging costs seconds
AUC_SEEDS = 15


def _auc(pos, neg):
    import numpy as np
    allv = np.concatenate([pos, neg])
    order = allv.argsort()
    ranks = np.empty_like(order, dtype=np.float64)
    ranks[order] = np.arange(1, len(allv) + 1)
    n1, n0 = len(pos), len(neg)
    return (ranks[:n1].sum() - n1 * (n1 + 1) / 2) / (n1 * n0)


def learnable_tags(conn):
    #scored on the vectors already in the database. the current model is the
    #RULER here, not the product: it only picks which labels are worth training
    #on.
    #
    #typed applications only, a tag being judged on the population it is trained
    #on and mine_tag_pairs being typed. counting inherited rows would score each
    #tag over its whole subtree, looser than where the pairs come from
    import numpy as np
    rows = conn.execute("""
        WITH one AS (SELECT oracle_id FROM lines WHERE NOT whole GROUP BY oracle_id HAVING count(*) = 1)
        SELECT l.oracle_id, l.embedding FROM lines l JOIN one o ON o.oracle_id = l.oracle_id
        WHERE NOT l.whole
    """).fetchall()
    ix, vecs = {}, []
    for oid, emb in rows:
        ix[oid] = len(vecs)
        vecs.append(np.asarray(emb.to_list() if hasattr(emb, "to_list") else emb, dtype=np.float32))
    V = np.vstack(vecs)
    V /= np.linalg.norm(V, axis=1, keepdims=True) + 1e-9
    bytag = {}
    for oid, tag in conn.execute("SELECT oracle_id, tag FROM card_tags WHERE NOT inherited"):
        if oid in ix:
            bytag.setdefault(tag, []).append(ix[oid])
    keep, scores = set(), {}
    for tag, members in sorted(bytag.items()):
        if len(members) < 10:
            continue   #too few to judge, and too few to teach
        draws = []
        for s in range(AUC_SEEDS):
            #a fresh generator per draw, so a tag's score does not depend on how
            #many tags were scored before it. seeded off the draw NUMBER: python
            #randomizes string hashing per process, so hash(tag) would not
            #reproduce between runs
            rng = np.random.default_rng(1000 + s)
            m = np.array(sorted(members))
            rng.shuffle(m)
            cut = max(3, len(m) // 3)
            centroid = V[m[cut:]].mean(axis=0)
            centroid /= np.linalg.norm(centroid) + 1e-9
            member = np.zeros(len(V), dtype=bool)
            member[m] = True
            neg = rng.choice(np.flatnonzero(~member), size=800, replace=False)
            draws.append(_auc(V[m[:cut]] @ centroid, V[neg] @ centroid))
        a = float(np.mean(draws))
        scores[tag] = a
        if a >= LEARNABLE_AUC:
            keep.add(tag)
    return keep, scores


def mine_tag_pairs(conn, exam):
    #(line, tag) positives from cards whose whole text is one line, so the tag
    #belongs to that line with no inference.
    #
    #ITS OWN SEED, so the held out split does not depend on how many random calls
    #the miners above made. otherwise --tags-only and a full run disagree about
    #the split, and a test set that moves with an unrelated regex is not one
    random.seed(1113)

    from make_tagreview import trainable_tags
    _, scores = learnable_tags(conn)
    keep, rescued, removed = trainable_tags(scores, LEARNABLE_AUC)
    print("  " + str(len(keep)) + " of " + str(len(scores)) + " tags are trainable ("
          + str(len({t for t, a in scores.items() if a >= LEARNABLE_AUC})) + " cleared AUC "
          + str(LEARNABLE_AUC) + ", the review rescued " + str(len(rescued))
          + " and pulled " + str(len(removed)) + ")")
    desc = {r[0]: r[1] for r in conn.execute("SELECT tag, description FROM tags")}

    def tag_text(t):
        d = (desc.get(t) or "").strip()
        return t + ": " + d if d else t

    rows = conn.execute("""
        WITH one AS (SELECT oracle_id, min(line_text) AS lt FROM lines
                     WHERE NOT whole GROUP BY oracle_id HAVING count(*) = 1)
        SELECT o.oracle_id, o.lt, ct.tag
        FROM one o JOIN card_tags ct ON ct.oracle_id = o.oracle_id AND NOT ct.inherited
    """).fetchall()
    bycard = {}
    for oid, lt, tag in rows:
        if lt in exam or tag not in keep:
            continue
        bycard.setdefault((oid, lt), set()).add(tag)

    #split by LINE TEXT, not by card. 305 of the held out lines print text
    #another single-line card also prints (functional reprints, the odd rename),
    #so splitting by card puts the same sentence on both sides and the model
    #trains on 18% of its own exam
    bytext = {}
    for (oid, lt), tags in bycard.items():
        bytext.setdefault(lt, []).append((str(oid), tags))
    groups = sorted(bytext.items())
    random.shuffle(groups)
    cut = int(len(groups) * TAG_TEST_FRACTION)
    test, train = groups[:cut], groups[cut:]

    pos = []
    for lt, cards in train:
        #one positive per (line, tag) however many cards print that line, the
        #lesson being about the sentence
        for t in sorted(set().union(*(tags for _, tags in cards))):
            pos.append((lt, tag_text(t), "line/tag"))
    #the test side stays one row per CARD, tags unmerged: two cards printing the
    #same line can carry different tags, and merging them would invent
    #supervision no human typed. the oracle_id is what keeps a row traceable back
    #to its line_tags rows, the text being ambiguous here by definition
    held = [{"oracle_id": oid, "line": lt, "tags": sorted(tags)}
            for lt, cards in test for oid, tags in cards]
    print("  " + str(len(groups)) + " distinct single-line texts over "
          + str(len(bycard)) + " cards, split " + str(len(train)) + " train / "
          + str(len(test)) + " test")
    trips = mine_sibling_negatives(conn, train, keep, tag_text)
    return pos, held, scores, trips


#how many triplets one line may contribute. a line carrying five tags with five
#siblings each would otherwise donate 25 rows and drown out lines with one
SIBS_PER_LINE = 4

#a sibling pair is only a real either/or if the two rarely share a card. above
#this the family is overlapping facets rather than a partition (removal-bounce
#sits with spot-removal on 87% of its cards, draw-engine with
#repeatable-pure-draw on 96%), so a card typed with one and not the other is
#decent odds of being an untyped gap and "this line is not spot-removal" would be
#false as often as not. 15.2% of unfiltered triplets come from pairs above 10%
SIB_COOCCUR = 0.10


def mine_sibling_negatives(conn, train, keep, tag_text):
    #(line, its tag, a sibling tag it does not have). siblings share a parent in
    #tagger's tree, so they are the near misses most in need of separating, and a
    #tagger choosing between children of one parent picks the right child: the
    #absence of a sibling is a DECISION rather than a gap.
    #
    #two exceptions, both filtered below:
    #  - the tree can contradict the negative. a card typed with a grandchild
    #    inherits the sibling (mill-any carries mill-opponent), 2.7% of triplets,
    #    so the exclusion set is every tag carried, typed or inherited
    #  - hub families overlap instead of partitioning, see SIB_COOCCUR
    #
    #only TRAINABLE siblings count: teaching "this line is not X" for an X the
    #model never learns to recognise spends capacity on nothing
    kids = {}
    for tag, parents in conn.execute("SELECT tag, parents FROM tags"):
        for p in (parents or ()):
            kids.setdefault(p, set()).add(tag)
    sibs = {}
    for children in kids.values():
        for c in children:
            if c in keep:
                sibs.setdefault(c, set()).update((children - {c}) & keep)

    #inheritance included, and checked against instead of the typed trainable
    #view the positives use: a tag does not have to be trainable, or typed by a
    #human, to make "is not" a lie
    all_of = {}
    for lt, tag in conn.execute("""
        WITH one AS (SELECT oracle_id, min(line_text) AS lt FROM lines
                     WHERE NOT whole GROUP BY oracle_id HAVING count(*) = 1)
        SELECT o.lt, ct.tag FROM one o JOIN card_tags ct ON ct.oracle_id = o.oracle_id
    """):
        all_of.setdefault(lt, set()).add(tag)

    #over every typed card in the corpus, not just the single-line ones
    tagged = {}
    for oid, tag in conn.execute("SELECT oracle_id, tag FROM card_tags WHERE NOT inherited"):
        tagged.setdefault(oid, set()).add(tag)
    count, co = {}, {}
    for tags in tagged.values():
        for t in tags:
            count[t] = count.get(t, 0) + 1
            for s in sibs.get(t, ()):
                if s in tags:
                    co[(t, s)] = co.get((t, s), 0) + 1

    out = []
    dropped_co = 0
    for lt, cards in train:
        mine = set().union(*(tags for _, tags in cards))
        carried = all_of.get(lt, mine)
        picked = []
        for t in sorted(mine):
            for s in sorted(sibs.get(t, set()) - carried):
                if co.get((t, s), 0) / max(count.get(t, 1), 1) > SIB_COOCCUR:
                    dropped_co += 1
                    continue
                picked.append((lt, tag_text(t), tag_text(s), "sibling tag"))
        random.shuffle(picked)
        out.extend(picked[:SIBS_PER_LINE])
    random.shuffle(out)
    print("  " + str(len(out)) + " sibling triplets over "
          + str(len(sibs)) + " tags with a trainable sibling ("
          + str(dropped_co) + " candidates dropped for co-occurrence over "
          + str(SIB_COOCCUR) + ")")
    return out


#---- retemplating: wizards saying the same thing in different decades ----

#renames wizards actually made, run backwards over modern oracle text: pairs
#meaning the same thing in very different words, on wizards' authority rather
#than a regex guess.
#
#each one has to be PURE, carrying no meaning of its own. bare "cast" -> "play"
#is historically correct and still not in the list, because it would sit "play
#this spell" beside "play an additional land" and blur casting into land drops.
#
#the object lands wrong on some ("Remove from the game target creature" where the
#card read "Remove target creature from the game"). synthetic word order, and the
#meaning is what the pair teaches
RETEMPLATE = [
    (r"\bmana value\b", "converted mana cost", "mana value rename"),
    (r"\bExile\b", "Remove from the game", "exile rename"),
    (r"\bexile\b", "remove from the game", "exile rename"),
    (r"\bexiled\b", "removed from the game", "exile rename"),
    (r"\bdies\b", "is put into a graveyard from play", "dies rename"),
    (r"\benters the battlefield\b", "comes into play", "enters rename"),
    (r"\benters\b", "comes into play", "enters rename"),
    (r"\bonto the battlefield\b", "into play", "battlefield rename"),
    (r"\bon the battlefield\b", "in play", "battlefield rename"),
    (r"\bthe battlefield\b", "play", "battlefield rename"),
    (r"\bWhenever you cast\b", "Whenever you play", "cast trigger rename"),
    (r"\bat the beginning of the end step\b", "at end of turn", "end step rename"),
    (r"\bAt the beginning of the end step\b", "At end of turn", "end step rename"),
]

#10k+ are minable, which would make them most of the positive signal on their
#own, and they teach a narrow lesson (one word swapped). the quota is per RENAME
#rather than per combination: bucketing on the combination makes forty-odd
#buckets and hands "battlefield + dies + exile + mana value" the same allowance
#as plain "enters", which is backwards
PER_RENAME = 200


def mine_retemplates(lines):
    out = []
    for line in lines:
        cur = line
        used = []
        for pat, repl, why in RETEMPLATE:
            new = re.sub(pat, repl, cur)
            if new != cur:
                used.append(why)
                cur = new
        if used and cur != line:
            out.append((line, cur, sorted(set(used))))
    picked = {}
    for why in sorted({w for _, _, used in out for w in used}):
        group = [r for r in out if why in r[2]]
        random.shuffle(group)
        for a, b, used in group[:PER_RENAME]:
            picked[(a, b)] = " + ".join(used)
    rows = [(a, b, why) for (a, b), why in picked.items()]
    random.shuffle(rows)
    return rows


#---- hard negatives: same trigger, unrelated effect ----

#magic templating is regular enough to split a line into its condition and its
#effect: "Whenever/When/At <trigger>, <effect>" and "<cost>: <effect>".
TRIGGER_RE = re.compile(r"^\s*(Whenever|When|At)\b(.*?),\s*(.+)$", re.S)
ACTIVATED_RE = re.compile(r"^\s*([^:.]{1,60}?):\s*(.+)$", re.S)


def split_condition(line):
    m = TRIGGER_RE.match(line)
    if m:
        return m.group(1) + m.group(2), m.group(3)
    m = ACTIVATED_RE.match(line)
    if m and "{" in m.group(1):
        return m.group(1), m.group(2)
    return "", line


def _bag(s):
    return set(re.findall(r"[a-z']+|\{[^}]*\}|\d+", s.lower()))


def _jaccard(a, b):
    ba, bb = _bag(a), _bag(b)
    return len(ba & bb) / len(ba | bb) if ba and bb else 0.0


#of the false positives where either side has a condition, 77% share the
#condition and differ in the effect: "At the beginning of your upkeep" opens
#three cards that exile your library, sacrifice an aura and add a time counter,
#and the model calls them alike. the trigger is the most repeated text in the
#game and says the least.
#
#the lesson is that a trigger is not SUFFICIENT, not that it is irrelevant, so
#this class produces negatives only and nothing pulls two triggers together
EFFECT_DIFF = 0.35   #jaccard above this and the effects are too alike to call different
PER_TRIGGER = 3      #"when this creature enters" would otherwise flood the class
TRIGGER_NEG_CAP = 1500


def mine_trigger_negatives(lines):
    groups = {}
    for line in lines:
        cond, eff = split_condition(line)
        if len(cond) > 12:
            groups.setdefault(" ".join(sorted(_bag(cond))), []).append((line, eff))
    out = []
    for _, group in sorted(groups.items()):
        if len(group) < 2:
            continue
        random.shuffle(group)
        picked = []
        for line, eff in group:
            if all(_jaccard(eff, other) < EFFECT_DIFF for _, other in picked):
                picked.append((line, eff))
        for i in range(len(picked)):
            for j in range(i + 1, len(picked)):
                out.append((picked[i][0], picked[j][0], "same trigger, different effect"))
        random.shuffle(out)
    random.shuffle(out)
    #one pair per trigger group first, so the cap spreads over many triggers
    seen = collections.Counter()
    kept = []
    for a, b, why in out:
        k = " ".join(sorted(_bag(split_condition(a)[0])))
        if seen[k] >= PER_TRIGGER:
            continue
        seen[k] += 1
        kept.append((a, b, why))
        if len(kept) >= TRIGGER_NEG_CAP:
            break
    return kept


#---- hard negatives: same opening, conflicting qualifier ----

#the mirror of the above: no shared clause should swamp a differing one.
#Thornspire Verge's "{T}: Add {G}. Activate only if you control a Mountain or a
#Forest" scored 100% against "{T}: Add {G}. Spend this mana only to cast a
#creature spell" - both tap for green, one gating when you may activate and the
#other what the mana buys.
#
#two guards, both needed:
#
#1. a trailing clause that ADDS is a rider, and riders are forgivable. Decree of
#   Pain is Rout plus a draw per creature, an upgrade rather than a different
#   card, so neither remainder may contain the other.
#2. the remainder must GATE the shared effect, not decorate it. "Destroy target
#   artifact. It can't be regenerated." against "Destroy target artifact. If you
#   controlled it, create three Goblins." passes guard one and is still a bad
#   negative, both being artifact removal
GATES = ("only if", "only to", "only during", "only when", "only any time",
         "unless you", "unless that", "unless an", "if you don't", "activate only",
         "spend this mana only")
QUALIFIER_CAP = 1200
PER_OPENING = 3


def _is_gate(text):
    low = text.lower()
    return any(g in low for g in GATES)


def _sentences(line):
    return [s.strip() for s in re.split(r"(?<=[.!])\s+", line) if s.strip()]


def mine_qualifier_negatives(lines):
    groups = {}
    for line in lines:
        sents = _sentences(line)
        if len(sents) < 2 or len(sents[0]) < 12:
            continue
        head = " ".join(sorted(_bag(sents[0])))
        groups.setdefault(head, []).append((line, " ".join(sents[1:])))
    out = []
    for _, group in sorted(groups.items()):
        if len(group) < 2:
            continue
        random.shuffle(group)
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                ra, rb = group[i][1], group[j][1]
                ba, bb = _bag(ra), _bag(rb)
                #one remainder containing the other is a rider, not a conflict
                if ba <= bb or bb <= ba:
                    continue
                if _jaccard(ra, rb) >= EFFECT_DIFF:
                    continue
                #and at least one side must gate the shared effect rather than
                #decorate it, or this fires on every pair of removal spells
                if not (_is_gate(ra) or _is_gate(rb)):
                    continue
                out.append((group[i][0], group[j][0], "same opening, conflicting qualifier"))
    random.shuffle(out)
    seen = collections.Counter()
    kept = []
    for a, b, why in out:
        k = " ".join(sorted(_bag(_sentences(a)[0])))
        if seen[k] >= PER_OPENING:
            continue
        seen[k] += 1
        kept.append((a, b, why))
        if len(kept) >= QUALIFIER_CAP:
            break
    return kept


#---- hard negatives: flips of real lines that look alike but mean the opposite ----

def swap_words(line, a, b, guards=()):
    #swap every standalone a for b and b for a, unless a guard phrase is present
    low = line.lower()
    for g in guards:
        if g in low:
            return None
    pat = re.compile(r"\b(" + a + "|" + b + r")\b", re.IGNORECASE)
    if not pat.search(line):
        return None

    def flip(m):
        w = m.group(0)
        out = b if w.lower() == a else a
        if w[0].isupper():
            out = out[0].upper() + out[1:]
        return out
    return pat.sub(flip, line)


def flip_loot_order(line):
    #"draw two cards, then discard two cards" <-> "discard two, then draw two"
    m = re.search(r"[Dd]raw (" + NUMBER_WORDS + r") cards?, then discard (" + NUMBER_WORDS + r") cards?", line)
    if m:
        d, n = m.group(1), m.group(2)
        repl = "discard " + n + (" card" if n in ("a", "an", "one") else " cards") \
             + ", then draw " + d + (" card" if d in ("a", "an", "one") else " cards")
        out = line[:m.start()] + repl + line[m.end():]
        return out[0].upper() + out[1:] if line[0].isupper() else out
    return None


#"same mechanism, flexible parameters" holds right until the parameter NULLS the
#effect: -X/-X is a sweeper, -1/-0 kills nothing, and untaught the model scores
#them 99% alike and makes Hell Swarm the top result for Toxic Deluge. only fires
#after "get"/"gets", so it never touches "-1/-1 counter", where a -1/-0 counter
#would be a card that does not exist rather than one meaning something else
def null_toughness(line):
    m = re.search(r"(\bgets?\s+-)(\d+|X)/-(\d+|X)", line)
    if not m or m.group(3) == "0":
        return None
    return line[:m.start()] + m.group(1) + m.group(2) + "/-0" + line[m.end():]


#who a restriction points AT, which the tap/untap and attack/block flips miss.
#Propaganda taxes the opponent's attack, Mogg Toady restricts its own body, and
#untaught, ten of Propaganda's top 20 come back as creatures with a drawback
def flip_restriction_target(line):
    if "can't attack you" in line:
        return line.replace("can't attack you", "you control can't attack")
    if "you control can't attack" in line:
        return line.replace("you control can't attack", "can't attack you")
    m = re.match(r"This creature can't attack\b", line)
    if m:
        return "Creatures can't attack you" + line[m.end():]
    return None


def make_negatives(lines):
    line_set = set(lines)
    negs = []
    for line in lines:
        candidates = [
            (flip_loot_order(line), "loot order flip"),
            (null_toughness(line), "toughness null"),
            (flip_restriction_target(line), "restriction target flip"),
            (swap_words(line, "tap", "untap", guards=("untap step", "doesn't untap", "don't untap")), "tap flip"),
            (swap_words(line, "enters", "dies"), "enters/dies flip"),
            (swap_words(line, "gain", "lose") if re.search(r"\b(?:gain|lose) " + NUMBER_WORDS + r" life", line) else None, "life flip"),
            (swap_words(line, "gains", "loses") if re.search(r"\b(?:gains|loses) " + NUMBER_WORDS + r" life", line) else None, "life flip"),
            (swap_words(line, "attack", "block", guards=("attack or block",)), "attack/block flip"),
            #permission vs restriction, triplet 31. skipped when a line has
            #both words, a double flip teaches nothing readable
            (swap_words(line, "may", "can't") if not ("may" in line.lower() and "can't" in line.lower()) else None,
             "may/can't flip"),
        ]
        #mana colour is payload, triplet 28. one step around the wheel so every
        #colour flips deterministically, and plenty land on real printed lines
        if "Add {" in line:
            sym = re.findall(r"\{([WUBRG])\}", line)
            if sym:
                wheel = "WUBRG"
                a = sym[0]
                b = wheel[(wheel.index(a) + 1) % 5]
                candidates.append((line.replace("{" + a + "}", "{" + b + "}"), "mana colour flip"))
            elif "{C}" in line:
                candidates.append((line.replace("{C}", "{G}"), "mana colour flip"))
        #a permission engine vs a property of one card, triplet 30
        if "this spell" in line and "its mana cost" in line:
            candidates.append((line.replace("this spell", "spells").replace("its mana cost", "their mana costs"),
                               "self/general flip"))
        elif " spells " in line and "their mana costs" in line:
            candidates.append((line.replace(" spells ", " this spell ", 1).replace("their mana costs", "its mana cost"),
                               "self/general flip"))
        if "graveyard to your hand" in line:
            candidates.append((line.replace("graveyard to your hand", "graveyard to the battlefield"), "hand/battlefield flip"))
        elif "graveyard to the battlefield" in line:
            candidates.append((line.replace("graveyard to the battlefield", "graveyard to your hand"), "hand/battlefield flip"))
        if "+1/+1 counter" in line:
            candidates.append((line.replace("+1/+1 counter", "-1/-1 counter"), "counter polarity flip"))
        elif "-1/-1 counter" in line:
            candidates.append((line.replace("-1/-1 counter", "+1/+1 counter"), "counter polarity flip"))

        for flipped, why in candidates:
            if flipped and flipped != line:
                #a flip landing on a real printed line is the best kind of
                #negative, but synthetic ones teach the same lesson
                negs.append((line, flipped, why + (" (real line)" if flipped in line_set else "")))
    return negs


def pairs_exam(db_url):
    #the anchor's line is quoted in the file, the other card only named, so
    #without a database this holds out what it can and SAYS SO rather than
    #pretending the holdout is complete
    from exam_pairs import parse_reports, PAIRS_MD
    entries = parse_reports(PAIRS_MD)
    held = set()
    named = set()
    for section, anchor_name, anchor_line, other_name in entries:
        held.add(clean_line(anchor_line, anchor_name))
        named.add(anchor_name)
        named.add(other_name)
    if not db_url:
        print("no database, so " + str(len(named)) + " exam_pairs.md cards are held out by anchor line only")
        return held
    import psycopg
    conn = psycopg.connect(db_url)
    rows = conn.execute("""
        SELECT l.line_text FROM lines l
        JOIN cards c ON c.oracle_id = l.oracle_id
        WHERE NOT l.whole AND c.name = ANY(%s)
    """, (sorted(named),)).fetchall()
    conn.close()
    for r in rows:
        held.add(r[0])
    print("holding out " + str(len(held)) + " lines from " + str(len(entries))
          + " exam_pairs.md entries across " + str(len(named)) + " cards")
    return held


def main():
    #remining the regex classes takes minutes for files nothing asked to change,
    #so --tags-only skips straight to the line -> tag half
    tags_only = "--tags-only" in sys.argv

    db_url = find_db_url()
    if tags_only and not db_url:
        print("--tags-only needs a database, tagger's labels are not in the bulk file")
        sys.exit(1)
    if db_url:
        print("reading lines from the site database...")
        lines = load_lines_from_db(db_url)
    else:
        lines = load_lines_from_scryfall()
    print(str(len(lines)) + " distinct lines")

    #the exam stays out of the textbook
    exam = set()
    for num, name, anchor, pos, neg in TRIPLETS:
        exam.add(clean_line(anchor[1], anchor[0]))
        for card, ls in (pos, neg):
            for l in ls:
                exam.add(clean_line(l, card))

    #exam_pairs.md is an exam too, and its entries name lines the miners target on
    #purpose: Toxic Deluge's "-X/-X" is an exam_pairs.md anchor and exactly what
    #null_toughness reads, so without this the model trains on a negative built
    #from the pair it is about to be tested on
    exam |= pairs_exam(db_url)

    lines = [l for l in lines if l not in exam]
    print(str(len(lines)) + " after holding out the eval lines")

    #routed to legacy/traindata, so regenerating them does not seed the live
    #folder with line-objective data
    LEGACY = {"train_pairs.jsonl", "train_negatives.jsonl",
              "train_triplets.jsonl", "train_retemplate.jsonl"}

    def dump(name, rows, keys):
        into = os.path.join(OUT_DIR, "legacy", "traindata") if name in LEGACY else DATA_DIR
        os.makedirs(into, exist_ok=True)
        path = os.path.join(into, name)
        with open(path, "w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(dict(zip(keys, row)), ensure_ascii=False) + "\n")
        print("wrote " + str(len(rows)) + " -> " + path)

    positives = negatives = retemplates = []
    if not tags_only:
        positives = mine_positives(lines)
        negatives = make_negatives(lines) + mine_trigger_negatives(lines) + mine_qualifier_negatives(lines)
        retemplates = mine_retemplates(lines)

        #dedupe (a,b) == (b,a)
        seen = set()
        positives = [p for p in positives if not (frozenset(p[:2]) in seen or seen.add(frozenset(p[:2])))]
        seen = set()
        negatives = [n for n in negatives if not (frozenset(n[:2]) in seen or seen.add(frozenset(n[:2])))]

        #triplets where an anchor has both a positive and a manufactured negative
        neg_by_anchor = {}
        for a, b, why in negatives:
            neg_by_anchor.setdefault(a, (b, why))
        triplets = []
        for a, b, why in positives:
            if a in neg_by_anchor:
                triplets.append((a, b, neg_by_anchor[a][0], why + " / " + neg_by_anchor[a][1]))

        dump("train_pairs.jsonl", positives, ["anchor", "positive", "why"])
        dump("train_negatives.jsonl", negatives, ["anchor", "negative", "why"])
        dump("train_triplets.jsonl", triplets, ["anchor", "positive", "negative", "why"])
        dump("train_retemplate.jsonl", retemplates, ["anchor", "positive", "why"])

    #tagger's labels are not in the bulk file, so this half needs the database
    if db_url:
        print("\nmining line -> tag pairs (tagger's own labelling)...")
        import psycopg
        from pgvector.psycopg import register_vector
        tconn = psycopg.connect(db_url)
        register_vector(tconn)
        tag_pos, tag_held, tag_scores, tag_trips = mine_tag_pairs(tconn, exam)
        tconn.close()
        dump("train_tag_pairs.jsonl", tag_pos, ["anchor", "positive", "why"])
        dump("train_tag_triplets.jsonl", tag_trips, ["anchor", "positive", "negative", "why"])
        path = os.path.join(DATA_DIR, "tag_testset.jsonl")
        with open(path, "w", encoding="utf-8") as f:
            for row in tag_held:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        print("wrote " + str(len(tag_held)) + " held out cards -> " + path)

        #written down rather than recomputed by whoever needs it next: exam_tags
        #reads it to know which tags a model is even being asked to predict, and
        #two callers agreeing beats two AUC passes quietly disagreeing
        path = os.path.join(DATA_DIR, "tag_learnability.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"threshold": LEARNABLE_AUC,
                       "model": "the vectors in the database at generation time",
                       "auc": {t: round(a, 4) for t, a in sorted(tag_scores.items())}}, f, indent=1)
        print("wrote " + str(len(tag_scores)) + " tag auc scores -> " + path)
    else:
        print("no database, skipping the line -> tag pairs")

    print("\nby type:")
    counts = {}
    for _, _, why in positives:
        counts[why] = counts.get(why, 0) + 1
    for _, _, why in retemplates:
        counts["retemplate: " + why] = counts.get("retemplate: " + why, 0) + 1
    for _, _, why in negatives:
        counts[why] = counts.get(why, 0) + 1
    for why in sorted(counts):
        print("  %-28s %d" % (why, counts[why]))

    print("\nsample positives:")
    for a, b, why in random.sample(positives, min(8, len(positives))):
        print("  [" + why + "]\n    " + a + "\n    " + b)
    print("\nsample negatives:")
    for a, b, why in random.sample(negatives, min(8, len(negatives))):
        print("  [" + why + "]\n    " + a + "\n    " + b)


if __name__ == "__main__":
    main()
