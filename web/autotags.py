#what the typed text on /custom is ABOUT: a list of tag chips, never a verdict.
#the page says out loud that the chips do not count toward the originality
#sentence, and they do not: that sentence is rules text alone.
#
#this is a port of rule_both in finetune/exam_autotags.py, which is what the
#numbers were measured on: 98% marked precision at 5 chips, list overlap 0.71
#against the stored tags. every constant below is that file's, and the two have
#to move together. what holds them together is the gate, tools/check_autotags.py,
#which scores real cards both ways and compares.
#
#PURE: scores in, chips out. the database work is views/custom.py's, because web
#deploys on its own and this file is what the tests can reach without one.

#a tag's score is the probe reading the typed line directly, blended with the
#vote of the lines nearest it. 0.7/0.3 was tuned on the dev half
PROBE_SHARE = 0.7

#the neighbours that vote, and how sharply a closer one outvotes a looser one.
#at 16 a near copy decides the vote almost alone, which is the point: a tag is
#worth showing when something almost identical carries it
SHARE_K = 10
SHARE_POWER = 16

#the exam reads each line's probe scores out of a file that keeps the top 60,
#and live there is no such cut. kept anyway so the two agree: 60 is far past the
#10 chips a card can show, and a tag below it can only ever reach the floor
PROBE_KEEP = 60

#a chip needs CHIP_BAR. a card short of CHIPS_LOW takes its best tags down to
#CHIP_FLOOR instead, so a keyword line still gets a chip or two when its
#neighbours agree on anything at all
CHIP_BAR = 0.40
CHIP_FLOOR = 0.15
CHIPS_LOW, CHIPS_HIGH = 2, 10

#with a type line typed in, a tag that lands on this type less than half a
#percent of the time it is used at all is dropped. it is the tags text alone
#cannot decide: Shadrix Silverquill's modes read like a spell's and draw
#single-target-instant-sorcery, and the type line is what says they are not
TYPE_FLOOR = 0.005

#a card's type as one word, in the order a type line has to be read: an Artifact
#Creature is a creature, and every land is a land
TYPES = ("Land", "Creature", "Instant", "Sorcery", "Artifact", "Enchantment", "Planeswalker",
         "Battle")


def card_type(type_line):
    #the FRONT face only, the way the exam reads it: a back face is a different
    #card and the visitor typed one card's worth of text
    head = (type_line or "").split("//")[0]
    for kind in TYPES:
        if kind in head:
            return kind
    return "other"


def share_scores(per_line):
    #per_line: one [(sim, tags), ...] per typed line, the SHARE_K nearest stored
    #lines and what each is about.
    #
    #a tag's score is the weighted share of the neighbours carrying it, which is
    #a plain estimate of how often it is right. the card takes the BEST over its
    #lines, so one ability nobody else has does not drown out the rest
    best = {}
    for neighbours in per_line:
        weights = [max(sim, 0.0) ** SHARE_POWER for sim, _ in neighbours]
        total = sum(weights) or 1.0
        carried = {}
        for weight, (_, tags) in zip(weights, neighbours):
            for tag in tags:
                carried[tag] = carried.get(tag, 0.0) + weight
        for tag, got in carried.items():
            if got / total > best.get(tag, 0.0):
                best[tag] = got / total
    return best


def probe_scores(per_line):
    #per_line: one {tag: probability} per typed line. best over the lines, the
    #same way share_scores rolls a card up
    best = {}
    for scores in per_line:
        for tag, p in sorted(scores.items(), key=lambda kv: -kv[1])[:PROBE_KEEP]:
            if p > best.get(tag, 0.0):
                best[tag] = p
    return best


def blend(probe, share):
    #a tag either half names. one with no probe of its own (58 tags are too rare
    #to have been learned) tops out at 1 - PROBE_SHARE, under CHIP_BAR, so it can
    #only ever arrive through the floor below
    return {tag: PROBE_SHARE * probe.get(tag, 0.0) + (1 - PROBE_SHARE) * share.get(tag, 0.0)
            for tag in set(probe) | set(share)}


def chips(scores, banned=(), type_shares=None, kind=None):
    #scores: {tag: score}. banned: the review's card and junk verdicts, which are
    #never chips. type_shares: {tag: {type: share of that tag's cards}}, read only
    #when the visitor typed a type line.
    #
    #dropped BEFORE ranking, so a tag nobody would show cannot take a slot from
    #one they would
    banned = set(banned)
    ranked = []
    for tag, score in scores.items():
        if tag in banned:
            continue
        if kind and type_shares is not None:
            #a tag with no row at all is kept: that is a tag too new to have been
            #counted, not one measured as wrong here
            per_type = type_shares.get(tag)
            if per_type is not None and per_type.get(kind, 0.0) < TYPE_FLOOR:
                continue
        ranked.append((score, tag))
    #by score, then by name, so two tags on exactly the same neighbours always
    #come out in the same order. the exam breaks that tie on its own tag ids, so
    #a tie sitting across the cut is the one place the two can disagree
    ranked.sort(key=lambda st: (-st[0], st[1]))

    keep = [(s, t) for s, t in ranked if s >= CHIP_BAR][:CHIPS_HIGH]
    if len(keep) < CHIPS_LOW:
        keep = [(s, t) for s, t in ranked if s >= CHIP_FLOOR][:CHIPS_LOW] or keep
    return {t: s for s, t in keep}
