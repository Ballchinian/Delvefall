# legacy

What no longer runs. The site ran on a "these two lines mean the same thing" model until 2026-07-22, when it retrained on (line, tag) pairs instead. Nothing in here serves the model that is live now.

`bakeoff_lines.py` is next door rather than in here: it is v1's bake-off and `train.py` still prints it as step 4 of a v2 run, a regression guard rather than a target.

| File | What it did |
| --- | --- |
| `make_keywords.py` | Mined keyword definitions out of Scryfall reminder text so the model could learn Hexproof and Shroud are cousins. Writes `traindata/train_keywords.jsonl` here beside it, which only `train.py --objective lines` ever reads |
| `exam_neighbours.py` | Step 6 of the v1 project: embed the whole database with the tuned model AND the old one, print the top matches for 14 ordinary searches side by side. It is how the launch-day complaint was caught in the wild (the old model's top match for Merfolk Looter's ability was the rummage line, at 98.2%) |
| `exam_neighbours.txt` | That run's printed output. Not published, since rerunning the script writes it again |
| `bakeoff_tags.py` | Picked the base model for the tag objective, which EmbeddingGemma had already won on lines, so it only confirmed the obvious. Here rather than deleted because it is the only thing that can rank one trained model against another on tags: point `MODELS` at two folders under `../models/` and it becomes the tag half of what `bakeoff_lines.py` does for lines. That run waits on a second v2 model existing |

## The training data, and what had to change to move it here

`traindata/` here holds the six files only `train.py --objective lines` reads. Like the live folder's, it is published:

| File | Rows | Where it came from |
| --- | --- | --- |
| `train_negatives.jsonl` | 21,445 | mined by `../make_training.py` |
| `train_pairs.jsonl` | 4,463 | mined by `../make_training.py` |
| `train_triplets.jsonl` | 1,432 | mined by `../make_training.py` |
| `train_retemplate.jsonl` | 1,215 | mined by `../make_training.py` |
| `train_keywords.jsonl` | 167 | mined by `make_keywords.py`, next door |
| `train_rewordings.jsonl` | 95 | **hand written, nothing can rebuild it** |

`testing_list/harvested.md` is here too: 1,190 cards' worth of false positives mined on 2026-07-19 and marked up. It was a review worksheet whose verdicts went into the training negatives and `exam_pairs.md`, so it is evidence rather than input.

## Why these are safe to have moved

The old vectors are still in `lines.embedding_v1`, the old model is on HuggingFace, and the repo is tagged `v1-rules-text` at the last commit before the swap, so reverting is renaming two database columns.

`train.py` prints `bakeoff_lines.py` as step 4 of a tag run, "as a regression guard, NOT a target", so the 26-triplet exam still runs against the current model.