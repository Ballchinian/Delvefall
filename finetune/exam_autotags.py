#the exam for inferring community tags from typed rules text, the concepts axis
#on /custom. offline, over the copy freeze_tagdata.py writes.
#    python finetune/exam_autotags.py --rule plan
#    python finetune/exam_autotags.py --rule <name> --half test
#
#a card's own stored line vectors stand in for typed text, with the card taken
#out of its own neighbours and out of the concept comparison. every commander
#legal card with a human tag and a line is examined, split on md5(oracle_id):
#even is dev, for tuning, odd is test, for the final numbers only. cards whose
#every line has an exact twin elsewhere get their own row, a twin's tags nearly
#giving the answer away.
#
#what is scored:
#  chips     how many, the share of cards landing on 2 to 10, and precision
#            against the card's tags with ancestors counted (a chip naming a
#            parent of a typed tag is true of the card). tagger is incomplete,
#            so precision is a floor
#  concept   concept uniqueness from the chips, minus the stored one
#  sentence  the /unique percentile from the chips against the stored one, in
#            points. baseline: rules text alone, the sentence /custom prints
#  list      top 20 of the strong tier anchored on the chips against the /search
#            list anchored on the human tags. baseline: rules text alone

import re
import os
import sys
import json
import time
import hashlib
import argparse
import statistics as st

import numpy as np
import scipy.sparse as sp

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "tagdata")
sys.path.insert(0, HERE)

#the search's hnsw LIMIT, and so the most neighbours a rule can ask for
K = 400

#web/app.py and ingest/tags.py, read here rather than imported: web/ needs a pool
BLEND = 0.5
UNIQUE_NOISE = 1e-6
INHERITED_WEIGHT = 0.5
TIER_CUT = 70
CONCEPT_LIMIT = 300
TOP = 20
TWIN = 0.9999
CHIPS_LOW, CHIPS_HIGH = 2, 10


def unit(m):
    return m / np.maximum(np.linalg.norm(m, axis=-1, keepdims=True), 1e-12)


def display(points, raw):
    #web/mirror.py's piecewise map, over arrays
    xs = np.array([p[0] for p in points])
    ys = np.array([p[1] for p in points])
    return np.rint(np.interp(np.clip(raw, 0.0, 1.0), xs, ys))


def raw_gate(points, pct):
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return float(np.interp(pct, ys, xs))


def line_weight(count):
    if count <= 5:
        return 1.0
    return 1.0 / (1.0 + np.log10(count / 5.0))


class Data:
    def __init__(self):
        t0 = time.time()
        read = lambda name: json.load(open(os.path.join(DATA, name + ".json"), encoding="utf-8"))
        meta = read("meta")
        self.mech_cal = json.loads(meta["mech_calibration"])
        self.concept_cal = json.loads(meta["concept_calibration"])

        cards = read("cards")
        self.card_ids = cards["oracle_id"]
        self.card_of = {oid: i for i, oid in enumerate(self.card_ids)}
        self.names = cards["name"]
        self.text = cards["oracle_text"]
        self.type_line = cards["type_line"]
        self.legal = np.array(cards["legal_commander"], dtype=bool)
        self.uniq = np.array([np.nan if u is None else u for u in cards["uniqueness"]], dtype=np.float64)
        self.cu = np.array([np.nan if u is None else u for u in cards["concept_uniqueness"]], dtype=np.float64)
        n_cards = len(self.card_ids)

        lines = read("lines")
        self.emb = unit(np.load(os.path.join(DATA, "embeddings.npy")))
        self.line_ids = lines["id"]
        self.line_text = lines["line_text"]
        self.owner = np.array([self.card_of[o] for o in lines["oracle_id"]], dtype=np.int32)
        self.nn_sim = np.array([np.nan if s is None else s for s in lines["nn_sim"]], dtype=np.float32)
        self.card_lines = {}
        for i, c in enumerate(self.owner):
            self.card_lines.setdefault(int(c), []).append(i)
        stats = read("line_stats")
        count = dict(zip(stats["line_text"], stats["count"]))
        self.weight = np.array([line_weight(count.get(t, 1)) for t in self.line_text], dtype=np.float32)

        tags = read("tags")
        self.tags = tags["tag"]
        self.tag_of = {t: i for i, t in enumerate(self.tags)}
        self.idf = np.array(tags["idf"], dtype=np.float64)
        self.card_count = np.array(tags["card_count"], dtype=np.int64)
        self.description = tags["description"]
        self.parents = [[self.tag_of[p] for p in ps if p in self.tag_of] for ps in tags["parents"]]
        self.n_cards_total = n_cards
        self._anc = {}

        ct = read("card_tags")
        self.typed = {}
        self.rolled = {}
        rows, cols, vals = [], [], []
        for oid, tag, inherited, w in zip(ct["oracle_id"], ct["tag"], ct["inherited"], ct["weight"]):
            c = self.card_of.get(oid)
            t = self.tag_of.get(tag)
            if c is None or t is None:
                continue
            self.rolled.setdefault(c, set()).add(t)
            if not inherited:
                self.typed.setdefault(c, set()).add(t)
            rows.append(c)
            cols.append(t)
            vals.append(w)
        m = sp.csr_matrix((np.array(vals, dtype=np.float64), (rows, cols)), shape=(n_cards, len(self.tags)))
        norms = np.sqrt(np.asarray(m.multiply(m).sum(axis=1)).ravel())
        norms[norms == 0] = 1.0
        self.card_vecs = sp.diags(1.0 / norms) @ m

        lt = read("line_tags")
        row_of_line = {lid: i for i, lid in enumerate(self.line_ids)}
        self.line_tags = {}
        for lid, tag in zip(lt["line_id"], lt["tag"]):
            i = row_of_line.get(lid)
            t = self.tag_of.get(tag)
            if i is not None and t is not None:
                self.line_tags.setdefault(i, set()).add(t)

        #the pools /unique ranks against, floored the way unique_standing floors
        pool = self.legal & ~np.isnan(self.uniq)
        u = self.uniq[pool]
        b = np.where(np.isnan(self.cu[pool]), u, (1 - BLEND) * u + BLEND * np.nan_to_num(self.cu[pool]))
        self.pool_rules = np.sort(np.where(u < UNIQUE_NOISE, 0.0, u))
        self.pool_blend = np.sort(np.where(b < UNIQUE_NOISE, 0.0, b))

        self.population = [c for c in range(n_cards)
                           if self.legal[c] and self.typed.get(c) and c in self.card_lines]
        self.twin = {c: bool(np.all(self.nn_sim[self.card_lines[c]] >= TWIN)) for c in self.population}
        self.load_neighbours()
        print("loaded in %.0fs: %d lines, %d cards, %d tags, %d examined"
              % (time.time() - t0, len(self.line_ids), n_cards, len(self.tags), len(self.population)))

    def half(self, c):
        return "dev" if int(hashlib.md5(self.card_ids[c].encode()).hexdigest(), 16) % 2 == 0 else "test"

    def load_neighbours(self):
        #exact cosine, own card masked, the K nearest in descending order. cached,
        #keyed on the frozen line count
        path = os.path.join(DATA, "neighbours_%d_%d.npz" % (K, len(self.line_ids)))
        want = sorted(i for c in self.population for i in self.card_lines[c])
        if os.path.exists(path):
            z = np.load(path)
            self.nb_row = {int(i): r for r, i in enumerate(z["lines"])}
            self.nb_idx, self.nb_sim = z["idx"], z["sim"]
            return
        print("neighbours for %d lines, once..." % len(want))
        idx = np.zeros((len(want), K), dtype=np.int32)
        sim = np.zeros((len(want), K), dtype=np.float32)
        block = 512
        t0 = time.time()
        for s in range(0, len(want), block):
            rows = want[s:s + block]
            sims = self.emb[rows] @ self.emb.T
            for r, i in enumerate(rows):
                sims[r, self.card_lines[int(self.owner[i])]] = -2.0
            part = np.argpartition(sims, -K, axis=1)[:, -K:]
            vals = np.take_along_axis(sims, part, axis=1)
            order = np.argsort(-vals, axis=1)
            idx[s:s + len(rows)] = np.take_along_axis(part, order, axis=1)
            sim[s:s + len(rows)] = np.take_along_axis(vals, order, axis=1)
            if s % (block * 10) == 0:
                print("  %d  %.0fs" % (s, time.time() - t0))
        np.savez(path, lines=np.array(want, dtype=np.int32), idx=idx, sim=sim)
        self.nb_row = {i: r for r, i in enumerate(want)}
        self.nb_idx, self.nb_sim = idx, sim

    def neighbours(self, line, k=K):
        r = self.nb_row[line]
        return self.nb_idx[r, :k], self.nb_sim[r, :k]

    def ancestors(self, t):
        if t in self._anc:
            return self._anc[t]
        out = {t}
        self._anc[t] = out
        for p in self.parents[t]:
            out |= self.ancestors(p)
        return out

    def anchor(self, direct):
        #ingest/tags.py's weights: idf for a chip, idf * INHERITED_WEIGHT for an
        #ancestor only the tree implies
        w = {}
        for t in direct:
            for a in self.ancestors(t):
                if a not in direct:
                    w[a] = self.idf[a] * INHERITED_WEIGHT
        for t in direct:
            w[t] = self.idf[t]
        vec = np.zeros(len(self.tags))
        for t, x in w.items():
            vec[t] = x
        n = np.linalg.norm(vec)
        return vec / n if n > 0 else None


def standing(pool, x):
    x = x if x >= UNIQUE_NOISE else 0.0
    below = int(np.searchsorted(pool, x, side="left"))
    return (1000 * below // len(pool)) / 10


class Lists:
    #find_similar's strong tier with no filters and the default sort, from the
    #cached neighbours
    def __init__(self, d, c):
        self.d = d
        self.c = c
        owners, scores, sims = [], [], []
        for q in d.card_lines[c]:
            idx, sim = d.neighbours(q)
            owners.append(d.owner[idx])
            scores.append(sim * d.weight[q])
            sims.append(sim)
        owners = np.concatenate(owners)
        scores = np.concatenate(scores)
        sims = np.concatenate(sims)
        order = np.lexsort((-sims, -scores))
        owners, scores, sims = owners[order], scores[order], sims[order]
        _, first = np.unique(owners, return_index=True)
        first = np.sort(first)  #best pair per card, in descending weighted score
        self.mech_owner = owners[first]
        self.mech_pct = display(d.mech_cal, sims[first])

    def rules_only(self):
        keep = self.mech_pct >= TIER_CUT
        return list(self.mech_owner[keep][:TOP]), dict(zip(self.mech_owner, self.mech_pct))

    def blended(self, vec):
        d = self.d
        raw = d.card_vecs @ vec
        raw[self.c] = -np.inf
        gate = raw_gate(d.concept_cal, TIER_CUT)
        near = np.argsort(-raw, kind="stable")[:CONCEPT_LIMIT]
        near = [int(o) for o in near if raw[o] >= gate]
        have = set(int(o) for o in self.mech_owner)
        entries = [(int(o), p) for o, p in zip(self.mech_owner, self.mech_pct)]
        entries += [(o, 0.0) for o in near if o not in have]
        conc = display(d.concept_cal, np.array([max(raw[o], 0.0) for o, _ in entries]))
        score = (1 - BLEND) * np.array([p for _, p in entries]) + BLEND * conc
        order = np.argsort(-score, kind="stable")
        strong = [entries[i][0] for i in order if np.rint(score[i]) >= TIER_CUT]
        return strong[:TOP], {entries[i][0]: np.rint(score[i]) for i in range(len(entries))}


def evaluate(d, rule, half, limit=None, show=0, quiet=False, cards=None):
    cards = cards if cards is not None else [c for c in d.population if d.half(c) == half]
    if limit:
        cards = cards[::max(1, len(cards) // limit)][:limit]
    rows = {"new": [], "twin": []}
    spent = 0.0
    shown = 0
    for c in cards:
        t0 = time.perf_counter()
        picked = rule(d, c)
        spent += time.perf_counter() - t0
        got = set(picked)
        typed, rolled = d.typed[c], d.rolled[c]
        r = {"n": len(got), "hit": len(got & rolled), "typed_hit": len(got & typed), "typed": len(typed)}

        truth_vec = d.card_vecs[c].toarray().ravel()
        vec = d.anchor(got) if got else None
        u = d.uniq[c]
        truth_pct = standing(d.pool_blend, (1 - BLEND) * u + BLEND * d.cu[c])
        r["base_gap"] = abs(standing(d.pool_rules, u) - truth_pct)
        if vec is not None:
            raw = d.card_vecs @ vec
            raw[c] = -np.inf
            cu = 1 - raw.max()
            r["cu_err"] = cu - d.cu[c]
            r["gap"] = abs(standing(d.pool_blend, (1 - BLEND) * u + BLEND * cu) - truth_pct)
        else:
            r["gap"] = r["base_gap"]

        lists = Lists(d, c)
        human, hpct = lists.blended(truth_vec)
        if human:
            base, _ = lists.rules_only()
            r["base_overlap"] = len(set(base) & set(human)) / len(human)
            if vec is not None:
                mine, mpct = lists.blended(vec)
                r["overlap"] = len(set(mine) & set(human)) / len(human)
                r["badge"] = [abs(mpct.get(o, 0) - hpct[o]) for o in human if o in mpct]
            else:
                r["overlap"] = r["base_overlap"]
        rows["twin" if d.twin[c] else "new"].append(r)

        if shown < show and not d.twin[c]:
            shown += 1
            print("\n== " + d.names[c] + "   " + (d.type_line[c] or ""))
            for q in d.card_lines[c]:
                print("   | " + d.line_text[q])
            print("   human: " + ", ".join(sorted(d.tags[t] for t in typed)))
            print("   chips: " + ", ".join(
                d.tags[t] + ("" if t in rolled else " (x)")
                for t in sorted(got, key=lambda t: -picked[t])))
    rows["ms"] = 1000 * spent / max(len(cards), 1)
    if not quiet:
        report(rows, spent / max(len(cards), 1))
    return rows


def summarize(R):
    def q(xs, p):
        return float(np.percentile(xs, p)) if xs else float("nan")

    def mean(xs):
        return st.mean(xs) if xs else float("nan")
    cu = [r["cu_err"] for r in R if "cu_err" in r]
    return {
        "cards": len(R),
        "chips": st.median([r["n"] for r in R]),
        "band": sum(1 for r in R if CHIPS_LOW <= r["n"] <= CHIPS_HIGH) / len(R),
        "none": sum(1 for r in R if not r["n"]) / len(R),
        "prec": mean([r["hit"] / r["n"] for r in R if r["n"]]),
        "micro": sum(r["hit"] for r in R) / max(sum(r["n"] for r in R), 1),
        "recall": mean([r["typed_hit"] / r["typed"] for r in R]),
        "cu_bias": mean(cu),
        "cu_err": st.median([abs(x) for x in cu]) if cu else float("nan"),
        "gap50": q([r["gap"] for r in R], 50),
        "gap90": q([r["gap"] for r in R], 90),
        "base50": q([r["base_gap"] for r in R], 50),
        "base90": q([r["base_gap"] for r in R], 90),
        "overlap": mean([r["overlap"] for r in R if "overlap" in r]),
        "base_overlap": mean([r["base_overlap"] for r in R if "base_overlap" in r]),
        "badge": st.median([b for r in R for b in r.get("badge", [])] or [float("nan")]),
    }


def report(rows, per_card):
    print()
    print("%-5s %6s %6s %6s %6s %6s %6s %6s %8s %8s %7s %7s %8s %8s"
          % ("", "cards", "chips", "2-10", "none", "prec", "micro", "recall", "cu bias", "cu |err|",
             "gap50", "gap90", "overlap", "badge"))
    for kind in ("new", "twin"):
        if not rows[kind]:
            continue
        s = summarize(rows[kind])
        print("%-5s %6d %6.1f %5.0f%% %5.0f%% %5.0f%% %5.0f%% %5.0f%% %+8.3f %8.3f %7.1f %7.1f %8.3f %8.1f"
              % (kind, s["cards"], s["chips"], 100 * s["band"], 100 * s["none"], 100 * s["prec"],
                 100 * s["micro"], 100 * s["recall"], s["cu_bias"], s["cu_err"], s["gap50"], s["gap90"],
                 s["overlap"], s["badge"]))
    s = summarize(rows["new"])
    print("rules text alone, new cards: gap50 %.1f  gap90 %.1f  overlap %.3f"
          % (s["base50"], s["base90"], s["base_overlap"]))
    print("rule time %.2fms a card" % (1000 * per_card))


#---- rules. each takes (data, card) and returns {tag index: score} ----

def rule_plan(d, c):
    #the rule that failed: lift over line_tags in 200 neighbours, every tag
    #eligible, FLOOR 1.5
    out = {}
    for q in d.card_lines[c]:
        idx, _ = d.neighbours(q, 200)
        hits = {}
        for j in idx:
            for t in d.line_tags.get(int(j), ()):
                hits[t] = hits.get(t, 0) + 1
        for t, h in hits.items():
            lift = (h / len(idx)) / (max(d.card_count[t], 1) / d.n_cards_total)
            if lift >= 1.5:
                out[t] = max(out.get(t, 0), lift)
    return out


#tuned on dev. a line's SHARE_K nearest lines on other cards vote with their
#line_tags, each weighted sim ** SHARE_POWER so a near copy outvotes a loose
#match. a tag's score is the weighted share of neighbours carrying it, the best
#over the card's lines: a plain estimate of how often the tag is right, where
#lift let a tag on 1 neighbour of 200 score 80x
SHARE_K = 10
SHARE_POWER = 16

#a chip needs CHIP_BAR. a card short of CHIPS_LOW takes its best tags down to
#CHIP_FLOOR instead, so a keyword line still gets a chip or two when its
#neighbours agree on anything at all
CHIP_BAR = 0.40
CHIP_FLOOR = 0.15

#the probe's share of the score in rule_both, the neighbours taking the rest
PROBE_SHARE = 0.7

#never chips, on top of the review's verdicts. they need the type line, which
#typed rules text does not carry: Shadrix Silverquill's modes read like a spell's
#and drew single-target-instant-sorcery. kept out of make_tagreview.md, which
#would also drop them from training, where auc 0.91 says the model learns them
UNSEEN = {"single-target-instant-sorcery"}

_probe = {}


def banned(d):
    #make_tagreview.md's card and junk verdicts are never chips. the dev half's
    #least precise tags were nearly all already there: out-of-color-token 26%,
    #doom-blade 7%, every *-with-set-mechanic 22-45%
    if "ban" not in _probe:
        from make_tagreview import read_verdicts
        _probe["ban"] = {d.tag_of[t] for t, v in read_verdicts().items()
                         if v in ("card", "junk") and t in d.tag_of}
        _probe["ban"] |= {d.tag_of[t] for t in UNSEEN if t in d.tag_of}
    return _probe["ban"]


def share_scores(d, c):
    best = {}
    for q in d.card_lines[c]:
        idx, sim = d.neighbours(q, SHARE_K)
        w = np.maximum(sim, 0.0) ** SHARE_POWER
        total = float(w.sum()) or 1.0
        acc = {}
        for j, x in zip(idx, w):
            for t in d.line_tags.get(int(j), ()):
                acc[t] = acc.get(t, 0.0) + x
        for t, a in acc.items():
            if a / total > best.get(t, 0.0):
                best[t] = a / total
    return best


def probe_scores(d, c):
    #make_tagprobe.py --crossfit, predicted by the half this card is not in
    if "idx" not in _probe:
        z = np.load(os.path.join(DATA, "probe_crossfit.npz"))
        _probe["idx"], _probe["p"] = z["idx"].astype(np.int64), z["p"].astype(np.float32)
    best = {}
    for q in d.card_lines[c]:
        for t, p in zip(_probe["idx"][q], _probe["p"][q]):
            if p > best.get(int(t), 0.0):
                best[int(t)] = float(p)
    return best


def chips(d, scores):
    ban = banned(d)
    ranked = sorted(((s, t) for t, s in scores.items() if t not in ban), reverse=True)
    keep = [(s, t) for s, t in ranked if s >= CHIP_BAR][:CHIPS_HIGH]
    if len(keep) < CHIPS_LOW:
        keep = [(s, t) for s, t in ranked if s >= CHIP_FLOOR][:CHIPS_LOW] or keep
    return {t: s for s, t in keep}


def rule_share(d, c):
    return chips(d, share_scores(d, c))


def rule_probe(d, c):
    return chips(d, probe_scores(d, c))


def both_scores(d, c):
    ps, ss = probe_scores(d, c), share_scores(d, c)
    return {t: PROBE_SHARE * ps.get(t, 0.0) + (1 - PROBE_SHARE) * ss.get(t, 0.0)
            for t in set(ps) | set(ss)}


def rule_both(d, c):
    return chips(d, both_scores(d, c))


RULES = {"plan": rule_plan, "share": rule_share, "probe": rule_probe, "both": rule_both}


#---- which tags need the type line, which typed rules text does not carry ----

#a card's type as one word, in the order a type line has to be read: an Artifact
#Creature is a creature, and every land is a land
TYPES = ("Land", "Creature", "Instant", "Sorcery", "Artifact", "Enchantment", "Planeswalker", "Battle")


def card_type(d, c):
    head = (d.type_line[c] or "").split("//")[0]
    for t in TYPES:
        if t in head:
            return t
    return "other"


def typeline_report(d, rule):
    #for every chip the rule hands out on the dev half: was it right, and what
    #type of card did it land on? a tag right on instants and wrong on creatures
    #is one the text alone cannot decide
    kind = {c: card_type(d, c) for c in range(len(d.card_ids))}
    carry = {}
    for c, ts in d.rolled.items():
        for t in ts:
            carry.setdefault(t, {}).setdefault(kind[c], 0)
            carry[t][kind[c]] += 1
    chips, right = {}, {}
    cards = [c for c in d.population if d.half(c) == "dev"]
    for i, c in enumerate(cards):
        for t in rule(d, c):
            chips.setdefault(t, {}).setdefault(kind[c], 0)
            chips[t][kind[c]] += 1
            if t in d.rolled[c]:
                right.setdefault(t, {}).setdefault(kind[c], 0)
                right[t][kind[c]] += 1
        if i % 2000 == 0:
            print("  %d/%d" % (i, len(cards)))
    rows = []
    for t, per in chips.items():
        n = sum(per.values())
        if n < 20:
            continue
        mine = right.get(t, {})
        held = carry.get(t, {})
        total = sum(held.values()) or 1
        #chips on a type holding under 2% of the tag's real cards
        off = sum(v for k, v in per.items() if held.get(k, 0) / total < 0.02)
        rows.append((off / n, t, n, sum(mine.values()) / n, per, mine, held, total))
    out = ["what share of each tag's chips land on a card type the tag hardly ever appears on.",
           "dev half, " + str(len(cards)) + " cards, " + str(len(rows)) + " tags with 20 chips or more.", ""]
    for off, t, n, prec, per, mine, held, total in sorted(rows, reverse=True)[:80]:
        out.append("%-38s %4d chips  %3.0f%% right  off-type %3.0f%%" % (d.tags[t], n, 100 * prec, 100 * off))
        out.append("    chips by type:  " + "  ".join(
            "%s %d/%d" % (k, mine.get(k, 0), per[k]) for k in TYPES + ("other",) if per.get(k)))
        out.append("    really on:      " + "  ".join(
            "%s %d%%" % (k, round(100 * held[k] / total)) for k in TYPES + ("other",)
            if held.get(k, 0) / total >= 0.02))
    path = os.path.join(HERE, "out", "autotag_typeline.txt")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")
    print("wrote " + path)


def typefilter_report(d):
    #web/autotags.py's type filter, which no other report here runs: a tag whose
    #share of cards on the typed type is under TYPE_FLOOR is dropped before
    #ranking. three arms from the same rule_both scores on the test half: no type,
    #the eight types, and land / non-land, non-land reading 1 minus the Land share.
    #shares count rolled tags the way tools/load_tag_probe.py does, over the cards
    #outside the test half, so no card votes on its own chips
    sys.path.insert(0, os.path.join(HERE, "..", "web"))
    from autotags import TYPE_FLOOR, card_type as web_type
    kind = {c: web_type(d.type_line[c]) for c in range(len(d.card_ids))}
    counts = {}
    for c, ts in d.rolled.items():
        if d.half(c) == "test":
            continue
        for t in ts:
            counts.setdefault(t, {}).setdefault(kind[c], 0)
            counts[t][kind[c]] += 1
    shares = {t: {k: n / sum(per.values()) for k, n in per.items()} for t, per in counts.items()}

    #each arm reads a card's type as a group and a tag's share as the sum over it.
    #eight and land are the two the verdict compares, the rest are coarser cuts
    everything = TYPES + ("other",)
    group = {"eight": {k: k for k in everything},
             "land": {k: k == "Land" for k in everything},
             "creature": {k: k == "Creature" for k in everything},
             "spell": {k: k in ("Instant", "Sorcery") for k in everything},
             "lcso": {k: k if k in ("Land", "Creature") else
                      "spell" if k in ("Instant", "Sorcery") else "other" for k in everything}}

    def share(t, c, arm):
        #a tag with no count is kept, as on the site
        if t not in shares:
            return 1.0
        mine = group[arm][kind[c]]
        return sum(v for k, v in shares[t].items() if group[arm][k] == mine)

    arms = ("none",) + tuple(group)

    def dealt(c, scores):
        return {arm: set(chips(d, scores if arm == "none" else
                               {t: s for t, s in scores.items() if share(t, c, arm) >= TYPE_FLOOR}))
                for arm in arms}

    cards = [c for c in d.population if d.half(c) == "test" and not d.twin[c]]
    got = {}
    for i, c in enumerate(cards):
        got[c] = dealt(c, both_scores(d, c))
        if i % 2000 == 0:
            print("  %d/%d" % (i, len(cards)))

    out = ["web's type filter, TYPE_FLOOR %g, rule_both on the test half: %d non-twin cards."
           % (TYPE_FLOOR, len(cards)),
           "right and wrong are against tagger, ancestors counted, as the exam counts precision.", ""]
    prec = {}
    out.append("%-8s %7s %6s %7s %7s" % ("arm", "chips", "mean", "prec", "micro"))
    for arm in arms:
        n = [len(got[c][arm]) for c in cards]
        hit = [len(got[c][arm] & d.rolled[c]) for c in cards]
        prec[arm] = st.mean([h / k for h, k in zip(hit, n) if k])
        out.append("%-8s %7d %6.2f %6.2f%% %6.2f%%" % (arm, sum(n), st.mean(n), 100 * prec[arm],
                                                      100 * sum(hit) / max(sum(n), 1)))
    out.append("")

    removed = {}
    for arm in arms[1:]:
        removed[arm] = [(c, t) for c in cards for t in got[c]["none"] - got[c][arm] - d.rolled[c]]
    for arm in arms[1:]:
        right_out = sum(len((got[c]["none"] - got[c][arm]) & d.rolled[c]) for c in cards)
        back_right = sum(len((got[c][arm] - got[c]["none"]) & d.rolled[c]) for c in cards)
        back_wrong = sum(len(got[c][arm] - got[c]["none"] - d.rolled[c]) for c in cards)
        by = {}
        for c, _ in removed[arm]:
            by[kind[c]] = by.get(kind[c], 0) + 1
        out.append("%s against none: removed %d wrong, %d right. put back %d right, %d wrong. precision %+.2f points"
                   % (arm, len(removed[arm]), right_out, back_right, back_wrong, 100 * (prec[arm] - prec["none"])))
        out.append("    wrong removed by card type: " + "  ".join(
            "%s %d" % (k, by[k]) for k in everything if by.get(k)))
        out.append("    catches %.0f%% of the wrong chips eight types removes"
                   % (100 * len(set(removed[arm]) & set(removed["eight"])) / max(len(removed["eight"]), 1)))
    out.append("")

    eight, land = set(removed["eight"]), set(removed["land"])
    caught = len(eight & land) / max(len(eight), 1)
    gap = 100 * (prec["land"] - prec["eight"])
    out.append("land / non-land removes %d of the %d wrong chips eight types removes (%.0f%%), and %d eight types does not"
               % (len(eight & land), len(eight), 100 * caught, len(land - eight)))
    out.append("precision land %+.2f points against eight types" % gap)
    missed = {}
    for c, t in eight - land:
        missed[kind[c]] = missed.get(kind[c], 0) + 1
    out.append("    eight types' removals land / non-land misses, by card type: " + "  ".join(
        "%s %d" % (k, missed[k]) for k in TYPES + ("other",) if missed.get(k)))
    gain = 100 * (prec["eight"] - prec["none"])
    out.append("PASS: land / non-land replaces the eight types" if caught >= 0.8 and gap >= -0.5 else
               "FAIL: land / non-land falls short of the eight types")
    if gain < 0.5:
        out.append("the eight types gain %.2f points over no type, under 0.5: any type input earns little" % gain)
    out.append("")

    marks, _, _ = read_marks(d)
    out.append("the %d hand-marked cards: marked-wrong chips, and marked-right chips, each arm removes" % len(marks))
    for arm in arms[1:]:
        wrong_gone, right_gone = [], []
        for c, wrong in marks:
            dealt_c = dealt(c, both_scores(d, c))
            gone = dealt_c["none"] - dealt_c[arm]
            wrong_gone += [d.names[c] + " " + d.tags[t] for t in gone & wrong]
            right_gone += [d.names[c] + " " + d.tags[t] for t in gone - wrong]
        out.append("  %s: wrong %d (%s)" % (arm, len(wrong_gone), ", ".join(wrong_gone) or "none"))
        out.append("  %s: right %d (%s)" % (arm, len(right_gone), ", ".join(right_gone) or "none"))

    path = os.path.join(HERE, "out", "autotag_typefilter.txt")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")
    print("\n".join(out))
    print("wrote " + path)


#---- the hand-marked half: precision as a person reads it ----

MARKS = "exam_autotags"


def marked_cards(d, rule, how_many, seed=11):
    #the same cards every run, drawn from the test half and never twins
    pool = sorted(c for c in d.population if d.half(c) == "test" and not d.twin[c])
    rng = np.random.default_rng(seed)
    picked = [pool[i] for i in rng.permutation(len(pool))[:how_many]]
    return [(c, rule(d, c)) for c in sorted(picked, key=lambda c: d.names[c])]


def write_marks(d, rule, how_many):
    #merges: a Wrong line already in the file wins, and a card new to the rule
    #arrives unjudged, so rerunning after a rule change loses no marking
    import examfile
    old = {}
    if os.path.exists(examfile.path(MARKS)):
        for e in examfile.read(MARKS).get("Chips", []):
            old[e["fields"].get("Card", "")] = e["fields"].get("Wrong", "?")
    out = ["# Are these the right tags for this text?", "",
           "The chips `exam_autotags.py` infers for cards it never saw, for a person to judge.",
           "Read at runtime by that script's `--marks`.", "",
           "## Chips", "",
           "**Wrong:** lists only the chips that are wrong about what the card does. Empty or",
           "`(none)` means every chip is right, `?` means not judged yet and the card is not",
           "scored. Notes go in [square brackets] and are ignored. A chip that is true but tagger",
           "never typed it counts as RIGHT: this file is what precision against the community tags",
           "cannot see.", ""]
    for n, (c, chips) in enumerate(marked_cards(d, rule, how_many), 1):
        out.append("%d." % n)
        out.append("    **Card:** " + d.names[c])
        for q in d.card_lines[c]:
            out.append("    **Line:** `" + d.line_text[q] + "`")
        out.append("    **Chips:** " + ", ".join(sorted(d.tags[t] for t in chips)))
        out.append("    **Wrong:** " + old.get(d.names[c], "?"))
        out.append("")
    with open(examfile.path(MARKS), "w", encoding="utf-8") as f:
        f.write("\n".join(out))
    print("wrote " + examfile.path(MARKS) + ", %d cards" % how_many)


def read_marks(d):
    #([(card, wrong tags)] for the judged cards, how many are unjudged, names that
    #are not tags)
    import examfile
    marks, unknown, unjudged = [], [], 0
    for e in examfile.read(MARKS).get("Chips", []):
        card = e["fields"].get("Card", "")
        mark = e["fields"].get("Wrong", "?").strip()
        if mark == "?" or card not in d.names:
            unjudged += 1
            continue
        wrong = set()
        #a note in brackets is for people. a name that is not a tag is a typo, and
        #silently reading it as nothing would score a wrong chip as right
        for part in re.sub(r"\[[^\]]*\]", "", mark).split(","):
            part = part.strip()
            if not part or part == "(none)":
                continue
            if part in d.tag_of:
                wrong.add(d.tag_of[part])
            else:
                unknown.append(card + ": " + part)
        marks.append((d.names.index(card), wrong))
    return marks, unjudged, unknown


def score_marks(d, rule):
    import examfile
    judged = tp = fp = 0
    tagger_tp = tagger_fp = 0
    gaps, called = [], []
    marks, unjudged, unknown = read_marks(d)
    for c, wrong in marks:
        card = d.names[c]
        chips = set(rule(d, c))
        judged += 1
        tp += len(chips - wrong)
        fp += len(chips & wrong)
        tagger_tp += len(chips & d.rolled[c])
        tagger_fp += len(chips - d.rolled[c])
        gaps += [d.tags[t] for t in chips - wrong - d.rolled[c]]
        called += [(card, d.tags[t]) for t in chips & wrong]
    if not judged:
        print("nothing judged yet in " + examfile.path(MARKS))
        return
    if unknown:
        print("NOT A TAG, so not counted: " + "; ".join(unknown))
    print("%d cards judged, %d not" % (judged, unjudged))
    print("precision as marked:  %.0f%% (%d right, %d wrong)" % (100 * tp / max(tp + fp, 1), tp, fp))
    print("precision by tagger:  %.0f%% (%d right, %d wrong)"
          % (100 * tagger_tp / max(tagger_tp + tagger_fp, 1), tagger_tp, tagger_fp))
    print("marked wrong: " + ", ".join(n + " " + t for n, t in called))
    print("%d chips are right but not on the card, so tagger missed them:" % len(gaps))
    print("  " + ", ".join(sorted(set(gaps))))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rule", default="plan", choices=sorted(RULES))
    ap.add_argument("--half", default="dev", choices=["dev", "test"])
    ap.add_argument("--limit", type=int, default=None, help="an even sample of this many cards")
    ap.add_argument("--show", type=int, default=0, help="print this many cards with their chips")
    ap.add_argument("--write-marks", type=int, default=0, help="write that many test cards to mark by hand")
    ap.add_argument("--marks", action="store_true", help="score against the marked file instead")
    ap.add_argument("--typeline", action="store_true", help="write out/autotag_typeline.txt")
    ap.add_argument("--typefilter", action="store_true",
                    help="web's type filter, eight types against land / non-land: out/autotag_typefilter.txt")
    args = ap.parse_args()
    d = Data()
    if args.write_marks:
        write_marks(d, RULES[args.rule], args.write_marks)
    elif args.marks:
        score_marks(d, RULES[args.rule])
    elif args.typeline:
        typeline_report(d, RULES[args.rule])
    elif args.typefilter:
        typefilter_report(d)
    else:
        evaluate(d, RULES[args.rule], args.half, args.limit, args.show)


if __name__ == "__main__":
    main()
