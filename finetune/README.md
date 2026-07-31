# The embedding model project

The site finds similar cards by turning every line of rules text into a list of numbers (an "embedding") where lines that mean similar things land close together. That trick has one famous weakness, and people found it on launch day: the model reads sentences a bit like a bag of words. "Draw a card, then discard a card" and "Discard a card: Draw a card" use the same words, so the model called them 98% similar. Any Magic player knows one is card selection and the other is a downside.

This folder is the project of fixing that, twice. **v1** taught a model that two lines mean the same thing. **v2**, live since 2026-07-22, teaches it what a line is ABOUT, which is what lets you pick one ability on a card and browse outward from it.

## Where the data comes from

| Source | What it is | What the site does with it |
| --- | --- | --- |
| [Scryfall](https://scryfall.com) bulk data | card names, rules text, type lines, images, prices, EDHREC ranks | downloaded once a day, stored, displayed |
| [Scryfall Tagger](https://tagger.scryfall.com) | community written tags describing what cards do | the concepts axis. A card's tags become a weighted vector, and two cards score on how much of that they share |
| this project | the embeddings, the line to tag attribution, the uniqueness scores | computed from the two above |

The embeddings are the part that is genuinely ours. Every line is cleaned (reminder text stripped, the card's own name swapped for "this card"), then run through the tuned model once, at ingest time. Nothing is embedded while you search. The tags are Tagger's work, not ours, which is why the concepts axis links back to them rather than pretending it invented the vocabulary.

## How this folder is laid out

Scripts sit at the top, named for what they do: `bakeoff_` picks a base model, `exam_` judges something already running, `make_` builds data, `train.py` trains, and `examfile.py` is the one reader they all share. Every hand-marked file carries the name of the script that owns it, so `exam_pairs.py` reads `testing_list/exam_pairs.md` and there is no second thing to remember.

| Folder | What is in it |
| --- | --- |
| `traindata/` | generated training data and the held-out test set, for the objective that is live |
| `testing_list/` | the hand-marked files. Scripts read these, people write them, and **nothing can rebuild them** |
| `out/` | run output that is safe to delete. `bakeoff_results.csv` only |
| `models/` | trained model folders, a gigabyte each. `train.py` saves here and the bake-offs load from here |
| `legacy/` | the same shape again, holding what no longer runs |

`testing_list/` against `out/` is the split that matters. Both look like results; only one is regenerable. A verdict in `make_tagreview.md` took an evening and no script can produce it a second time.

## Which model each file belongs to

Three models have shown results on the site. Only two were trained here.

| | What it is | Status |
| --- | --- | --- |
| stock `all-MiniLM-L6-v2` | off the shelf, never trained here | ran at launch. The "old model" the v1 sanity report scores against |
| **v1**, `--objective lines` | tuned EmbeddingGemma. Two lines mean the same thing | retired 2026-07-22, vectors kept in `lines.embedding_v1` |
| **v2**, `--objective tags` | tuned EmbeddingGemma. What a line is ABOUT | live |

| File | Era | Reads / writes |
| --- | --- | --- |
| `train.py` | both | `--objective` picks which |
| `make_training.py` | both | v2's files into `traindata/`, v1's into `legacy/traindata/` |
| `bakeoff_lines.py` | v1 | the exam, from `testing_list/bakeoff_lines.md` |
| `exam_tags.py` | v2 | `traindata/tag_testset.jsonl` |
| `make_tagreview.py` | v2 | reads and rewrites `testing_list/make_tagreview.md` |
| `legacy/bakeoff_tags.py` | v2 | ranks models on the tag objective. Waiting for a second v2 model to compare against |
| `legacy/make_keywords.py` | v1 | writes `legacy/traindata/train_keywords.jsonl` |
| `legacy/exam_neighbours.py` | v1 | writes `legacy/exam_neighbours.txt` |
| `exam_pairs.py` | neither | axis 1 as displayed, from `testing_list/exam_pairs.md` |
| `exam_concepts.py` | neither | axis 2, from `testing_list/exam_concepts.md` |
| `exam_attribution.py` | neither | `ingest/attribute.py`, from `testing_list/exam_attribution.md` |

`bakeoff_lines.py` is the one whose name reads wrong. It is v1's bake-off and it still runs: `train.py` prints it as step 4 of a v2 run, a regression guard rather than a target. So `legacy/` means "no longer runs", not "v1 era".

Every hand-marked file is parsed at runtime, so the file people edit is the file that scores and none of them can drift from the code. The four exams share one layout and one reader, `examfile.py`: an H1 saying what it scores and which script reads it, then `## Section` headings each stating what passing means, then numbered entries of `**Field:** value` lines and one italic reason. `make_tagreview.md` keeps its own shape because it is a verdict worksheet rather than an exam.

## What is published here

All of it, scripts and data both. Enough to rebuild every number below against your own database, and enough to argue with the judgement calls, which are the part that took the longest. Two exceptions, neither of them interesting: `models/` is 1.2GB, past what GitHub takes, and `legacy/exam_neighbours.txt` is a run's printed output that rerunning the script writes again.

# v1: teaching a model that two lines mean the same thing

## The exam

You can't pick a model on vibes, and the public leaderboards test the wrong thing (search engines, not "do these two abilities mean the same thing"). So the first artifact is an exam: hand-reviewed triplets, each an anchor line, a line that *should* match it, and a trap that looks nearly identical but means something else. Rummaging Goblin is Merfolk Looter's trap. Refocus (untap) is Pressure Point's (tap), and they differ by two letters.

It settled the site's philosophy of similarity in writing: **same mechanism, flexible parameters.** Numbers, colours and riders are forgivable; a flipped mechanism is not, even when the deck slot matches. Lightning Bolt and Murder both kill a creature and are still not "similar".

It started at 26 and grows whenever a user report catches the model out, since that is exactly the shape of an exam question. Five went in on 2026-07-15, so it stands at 31, and `bakeoff_lines.py` counts the list rather than being told how long it is. Every score below was measured against the original 26. The exam is never trained on.

## The bake-off, and the finding that shaped everything after

| Model | Score | Notes |
| --- | --- | --- |
| all-MiniLM-L6-v2 (the site's model at the time) | 20/26 | rates the rummage trap 98.2% similar to Merfolk Looter |
| bge-small-en-v1.5 | 20/26 | the planned upgrade. Identical score, same failures |
| gte-modernbert-base | 19/26 | worse than what we had |
| EmbeddingGemma-300m | 21/26 | only stock model to pass loot vs rummage, barely (+1.5) |
| Qwen3-Embedding-0.6B | 21/26 | scores compress into a 75-98% band that would break the match % display |

**Every model failed the same questions.** Tap vs untap and "reanimate reworded" went 0 for 5. They were all trained on the same internet and learned the same habit of treating word-swapped sentences as paraphrases.

## The textbook

The exam is 26 questions; the textbook needs thousands, almost all generated from the site's own distinct rules lines. It teaches four things:

- **Parameters are flexible.** Lines differing only by numbers, riders or scope: "Draw two cards" against "Draw three cards", Unsummon against Vapor Snag.
- **Mechanisms are not.** Real lines with exactly one mechanism flipped: tap for untap, enters for dies, gain for lose, hand for battlefield, attack for block, draw-then-discard reversed. A good fraction of the flips turn out to be real printed cards, which is the best kind of lesson.
- **Function over phrasing.** Wizards renamed the same effects repeatedly over thirty years, so running those renames backwards over modern text produces same-meaning pairs whose authority is Wizards rather than a regex guess.
- **A shared clause must not swamp a differing one.** Of the harvested false positives where either side had a trigger condition at all, **77% shared the condition and differed in the effect.** "At the beginning of your upkeep" opens one card that exiles your library, one that sacrifices an Aura and one that adds a time counter, and the model called them alike.

Every line in the exam is excluded from all of it, so passing can never be memorization.

## Training and the rematch

Runs on a free Colab GPU in under an hour, on EmbeddingGemma-300m, the strongest small model from the bake-off. Three lessons with three matched losses: pairs pull together, triplets pull and push at once, and the flips go through a contrastive loss that explicitly pushes near-identical wordings apart, which is the exact ability no stock model has. Rare classes are oversampled, bloated ones capped. The base expects a task prompt, so the tuned model was trained with one and must always be used with it.

| Model | Score |
| --- | --- |
| **mtg-tuned EmbeddingGemma** | **25/26** |
| EmbeddingGemma-300m / Qwen3-0.6B | 21/26 |
| all-MiniLM-L6-v2 / bge-small | 20/26 |

Both impossible questions fell: tap vs untap by +35 points, the reanimate rewording by +31. The margins are the real story. Stock models that passed loot vs rummage did it by a fragile 1-2 points; the tuned model passes by +12.5, and rates Blood Artist against Soul Warden (dies vs enters) as *negatively* similar, the model saying "opposites" rather than "close call". One question regressed, a fair trade for five fixes.

## The sanity check

25/26 could still hide a model that went weird everywhere else, so `legacy/exam_neighbours.py` embeds the entire database with both the tuned and the old model and prints the top matches for 14 ordinary searches side by side. The neighborhoods are sane, and the report catches the old model doing the launch day complaint in the wild: its #1 match for Merfolk Looter's ability is the rummage line, at 98.2%. The tuned model's top matches are all true looting variants. Same story for lifegain, reanimation and discard.

# v2: teaching a model what a line is about

v1 answered "do these two lines mean the same thing", which is the right target for ranking and the wrong one for browsing. "What is this line ABOUT" is what lets you pick one ability and search from it, the one thing neither Scryfall nor Tagger can do: both are card-level, so a card tagged three ways gives you no way to know which tag belongs to which ability.

So v2 trains on (line, tag) pairs instead of (line, line), using the eleven thousand cards whose entire rules text is a single line. On those, every tag a human typed belongs to that one line with no inference required, which is a large amount of supervision nobody had to label. The exam is the same shape as v1's: hold cards back, then ask whether the model ranks the right tags first for text it has never seen.

Which tags it is allowed to learn is a separate question, and not one a model can answer about its own successor. `make_tagreview.py` builds the worksheet and `testing_list/make_tagreview.md` holds the hand-judged verdicts.

Results: the tag half of the site went from 47% to 78% on `exam_tags.py`, line attribution from 88% to 94% precision, and the v1 line-to-line exam held its ground, which is the one that would have caught it forgetting what it already knew.

That 94% was measured on `exam_attribution.py` when it held three hand-labelled cards. The exam has since grown to nine, and on all nine v2 scores **88% precision and 84% recall**. Those three still score 94%, so nothing regressed; the exam simply got harder, and the wider number is the honest one to beat.

# Shipping a retrain

`train.py` prints a pointer here rather than the steps, because the dangerous one needs more room than a Colab log gives it.

**Leave `EMBED_MODEL` alone.** Swapping it makes the ingest overwrite `lines.embedding` in place, and the old vectors cannot be recovered without rerunning the old model over the whole corpus. The second column exists precisely so a new model can be judged without touching what the site is serving.

Under `--objective tags`, in this order:

1. Upload to a **new** Hugging Face repo from the same Colab session, before the runtime dies. The old repo is the rollback, so leave it alone: `m = SentenceTransformer(out_dir)` then `m.push_to_hub('you/mtg-tagtuned-embeddinggemma-300m', private=True)`.
2. On a machine with `DATABASE_URL`, fill the second column: `python -m ingest.backfill_embeddings --model <the new repo> --index`. This leaves `lines.embedding` exactly as the site is serving it.
3. Judge it against that column: `EMBED_COLUMN=embedding_v2 python -m finetune.exam_tags`. Compare like with like. The headline is the **centroid** recall @10, which is what the 47% and 78% above are. The `tags_cosine_recall@10` that `train.py` prints during training is text retrieval and is a different number.
4. `python finetune/bakeoff_lines.py` as a regression guard, not a target. A drop here is the umbrella tags teaching structure over meaning.
5. Only if all of that holds: set `EMBED_COLUMN=embedding_v2` on the web service to browse real searches. Unset it to revert instantly.

Under `--objective lines`, there is no column dance: copy the saved folder into `models/`, add it to `MODELS` in `bakeoff_lines.py`, and rerun that for the per-triplet exam.
