# legacy

The v1 model's own tools. The site ran on a "these two lines mean the same
thing" model until 2026-07-22, when it retrained on (line, tag) pairs instead.
Nothing in here serves the model that is live now.

| File | What it did |
| --- | --- |
| `make_keywords.py` | Mined keyword definitions out of Scryfall reminder text so the model could learn Hexproof and Shroud are cousins. Writes `traindata/train_keywords.jsonl` here beside it, which only `train.py --objective lines` ever reads |
| `exam_neighbours.py` | Step 6 of the v1 project: embed the whole database with the tuned model AND the old one, print the top matches for 14 ordinary searches side by side. It is how the launch-day complaint was caught in the wild (the old model's top match for Merfolk Looter's ability was the rummage line, at 98.2%) |
| `sanity_report.txt` | That run's output, kept because it is the evidence, not a cache |

## The training data came too, and what had to change first

`traindata/` here holds the six files only `train.py --objective lines` reads:

| File | Rows | Where it came from |
| --- | --- | --- |
| `train_negatives.jsonl` | 21,445 | mined by `../make_training.py` |
| `train_pairs.jsonl` | 4,463 | mined by `../make_training.py` |
| `train_triplets.jsonl` | 1,432 | mined by `../make_training.py` |
| `train_retemplate.jsonl` | 1,215 | mined by `../make_training.py` |
| `train_keywords.jsonl` | 167 | mined by `make_keywords.py`, next door |
| `train_rewordings.jsonl` | 95 | **hand written, nothing can rebuild it** |

`testing_list/harvested.md` is here too: 1,190 cards' worth of false positives
mined on 2026-07-19 and marked up by hand. No script has ever read it. It was a
review worksheet whose verdicts went into the training negatives and `pairs.md`,
so it is evidence rather than input.

**Moving data out of `traindata/` is not safe by default, and that is the thing
to know before touching any of it.** `train.py`'s `load_jsonl` **fails soft**: a
file it cannot find prints "missing X, skipping it" and returns an empty list.
So a moved file does not break a run, it quietly trains on less and hands back a
model that looks fine until it is tested.

Three changes make the move safe, and all three have to stay true together:

- `../train.py` `load_jsonl` looks in `traindata/` **then** `legacy/traindata/`
- `../make_training.py` writes its four line-objective files back into here
- `make_keywords.py` writes `train_keywords.jsonl` into here

Verified after the move: all six files load, 28,817 rows between them.

## Why these are safe to have moved

Rollback to v1 never retrains. The old vectors are still in
`lines.embedding_v1`, the old model is on HuggingFace, and the repo is tagged
`v1-rules-text` at the last commit before the swap, so reverting is renaming two
database columns. Nothing here is on that path.

`bakeoff_lines.py` is the one that looks like it belongs here and does not:
`train.py` prints it as step 4 of a tag run, "as a regression guard, NOT a
target", so the 26-triplet exam still runs against the current model.

## Running one anyway

Both still work, from the repo root, the same as before:

    python finetune/legacy/make_keywords.py
    python finetune/legacy/exam_neighbours.py

Their path handling was adjusted for the extra folder: each one reaches the repo
root two levels up now, `exam_neighbours` imports `make_training` out of
`finetune/`, and `make_keywords` writes `train_keywords.jsonl` into
`traindata/` here rather than into the live folder next door.

`exam_neighbours` loads the tuned model out of `../models/`, which is where
trained models live since the folder was tidied. It writes `sanity_report.txt`
beside itself, here.
