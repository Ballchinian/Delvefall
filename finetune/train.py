#fine tunes an embedding model on the generated mtg training data.
#
#--objective picks what it learns:
#   lines  lines that mean the same thing land close together. what the site
#          shipped. attribution reads tags off it indirectly, at 88%/82%
#   tags   a line lands close to the text of its tags, trained on single-line
#          cards where a human's tag can only belong to that line
#   both   a mix, experimental
#
#three losses under --objective lines:
#   pairs          mined variants, keyword meanings, rewordings   pull together
#   triplets       anchor, variant, flipped anchor                pull and push
#   labeled flips  anchor vs flipped, label 0                     push apart
#
#the exam triplets are a HELD OUT evaluator, never training data, and under
#--objective tags a regression guard rather than a target.
#
#the judge is recall @10 on the held out cards, printed as training goes and
#measured properly by python -m finetune.exam_tags

import os
import sys
import json
import random
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

random.seed(7)
HERE = os.path.dirname(os.path.abspath(__file__))

#rare classes oversampled and bloated ones capped, so enters/dies and may/can't
#do not drown the rest out. the biggest multipliers are the classes rarest in the
#mine, each answering a failure users actually hit
CAP = 1500
OVERSAMPLE = {"loot order flip": 5, "attack/block flip": 2, "hand/battlefield flip": 2,
              "self/general flip": 5, "mana amount variant": 5, "subtype variant": 3,
              "etb wrapper": 2,
              #both mine rare and both answer a failure at rank 1, so both are
              #lifted into the 500-800 band
              "restriction target flip": 5, "toughness null": 2,
              #only 179 after the guards keeping it off removal pairs, but it
              #answers 8% of the harvested false positives. its partner "same
              #trigger, different effect" hits the cap unaided
              "same opening, conflicting qualifier": 3}

#the tag objective flattens for the opposite reason: seven tags carry 23% of the
#36k pairs (activated-ability alone is 1843), so uncapped a quarter of training
#goes on labels that say little, while 296 of 654 tags have under 20 pairs each
TAG_CAP = 300


def load_tag_pairs():
    rows = load_jsonl("train_tag_pairs.jsonl")
    by_tag = {}
    for r in rows:
        by_tag.setdefault(r["positive"], []).append(r)
    out = []
    for tag, group in sorted(by_tag.items()):
        random.shuffle(group)
        out.extend(group[:TAG_CAP])
    random.shuffle(out)
    capped = sum(1 for g in by_tag.values() if len(g) > TAG_CAP)
    print("  %d pairs over %d tags, %d tags capped at %d"
          % (len(out), len(by_tag), capped, TAG_CAP))
    return out


#both folders are searched so neither objective's files have to move. a missing
#file is SKIPPED rather than fatal, so a misplaced one silently trains on less
def load_jsonl(name):
    for folder in (os.path.join(HERE, "traindata"),
                   os.path.join(HERE, "legacy", "traindata")):
        path = os.path.join(folder, name)
        if os.path.exists(path):
            return [json.loads(l) for l in open(path, encoding="utf-8")]
    print("missing " + name + ", skipping it")
    return []


def balance(rows):
    by_why = {}
    for r in rows:
        why = r.get("why", "?").replace(" (real line)", "")
        by_why.setdefault(why, []).append(r)
    out = []
    for why, group in by_why.items():
        random.shuffle(group)
        group = group[:CAP] * OVERSAMPLE.get(why, 1)
        out.extend(group)
        print("  %-24s %d" % (why, len(group)))
    random.shuffle(out)
    return out


def main():
    ap = argparse.ArgumentParser()
    #the tuned line-to-line model, not a stock base: already 768 dims so nothing
    #downstream moves, and it already knows tap from untap.
    #
    #the tag bakeoff puts five stock bases in a 2.5 point band zero shot and the
    #leader is 384 dims, which would mean changing EMBED_DIMS, the column type
    #and the hnsw index for a lead unlikely to survive fine tuning.
    #
    #laptop smoke test: --model sentence-transformers/all-MiniLM-L6-v2
    ap.add_argument("--model", default="BallchinianMan/mtg-tuned-embeddinggemma-300m")
    ap.add_argument("--epochs", type=int, default=1)
    ap.add_argument("--batch", type=int, default=0, help="0 picks one based on model size")
    ap.add_argument("--objective", default="tags", choices=["tags", "lines", "both"],
                    help="tags is the retarget, lines is what the site shipped")
    ap.add_argument("--limit", type=int, default=0,
                    help="train on this many rows per dataset, for smoke testing the wiring")
    args = ap.parse_args()

    import torch
    from datasets import Dataset
    from sentence_transformers import SentenceTransformer, SentenceTransformerTrainer, SentenceTransformerTrainingArguments
    #v5 moved these under .sentence_transformer. both paths are tried because
    #colab installs whatever is latest that day, and a version bump should not be
    #what fails an hour into a training run
    try:
        from sentence_transformers.sentence_transformer.losses import (
            MultipleNegativesRankingLoss, ContrastiveLoss)
        from sentence_transformers.sentence_transformer.evaluation import (
            TripletEvaluator, InformationRetrievalEvaluator)
        from sentence_transformers.sentence_transformer.training_args import BatchSamplers
    except ImportError:
        from sentence_transformers.losses import MultipleNegativesRankingLoss, ContrastiveLoss
        from sentence_transformers.evaluation import TripletEvaluator, InformationRetrievalEvaluator
        from sentence_transformers.training_args import BatchSamplers
    from bakeoff_lines import TRIPLETS
    from common.cards import clean_line

    is_gemma = "gemma" in args.model.lower()
    #embeddinggemma is trained to see a task prompt, so train and eval with the
    #same one. the tuned model must then be used with this prefix FOREVER
    prefix = "task: sentence similarity | query: " if is_gemma else ""
    batch = args.batch or (16 if is_gemma else 64)

    print("loading data...")
    train_sets, losses = {}, {}

    if args.objective in ("tags", "both"):
        print("line -> tag pairs:")
        tag_pairs = load_tag_pairs()
        if not tag_pairs:
            print("no train_tag_pairs.jsonl. build it with:")
            print("  python finetune/make_training.py --tags-only")
            sys.exit(1)
        train_sets["tags"] = Dataset.from_dict({
            "anchor": [prefix + r["anchor"] for r in tag_pairs],
            "positive": [prefix + r["positive"] for r in tag_pairs],
        })

        #near misses as EXPLICIT negatives. in-batch negatives rarely supply
        #these, a random other row usually being nothing like the anchor
        tag_trips = load_jsonl("train_tag_triplets.jsonl")
        if tag_trips:
            print("  plus " + str(len(tag_trips)) + " sibling triplets")
            train_sets["tag_triplets"] = Dataset.from_dict({
                "anchor": [prefix + r["anchor"] for r in tag_trips],
                "positive": [prefix + r["positive"] for r in tag_trips],
                "negative": [prefix + r["negative"] for r in tag_trips],
            })

    if args.objective in ("lines", "both"):
        pairs = (load_jsonl("train_pairs.jsonl") + load_jsonl("train_keywords.jsonl")
                 + load_jsonl("train_rewordings.jsonl") + load_jsonl("train_retemplate.jsonl"))
        negatives = load_jsonl("train_negatives.jsonl")
        triplets = load_jsonl("train_triplets.jsonl")

        print("positives by class:")
        pairs = balance(pairs)
        print("negatives by class:")
        negatives = balance(negatives)

        train_sets["pairs"] = Dataset.from_dict({
            "anchor": [prefix + r["anchor"] for r in pairs],
            "positive": [prefix + r["positive"] for r in pairs],
        })
        train_sets["triplets"] = Dataset.from_dict({
            "anchor": [prefix + r["anchor"] for r in triplets],
            "positive": [prefix + r["positive"] for r in triplets],
            "negative": [prefix + r["negative"] for r in triplets],
        })
        #every flip is a 0, with an equal helping of positives as 1s so the
        #contrastive loss sees both sides
        ones = random.sample(pairs, min(len(pairs), len(negatives)))
        train_sets["labeled"] = Dataset.from_dict({
            "sentence1": [prefix + r["anchor"] for r in negatives] + [prefix + r["anchor"] for r in ones],
            "sentence2": [prefix + r["negative"] for r in negatives] + [prefix + r["positive"] for r in ones],
            "label": [0] * len(negatives) + [1] * len(ones),
        })

    #the target under --objective lines, a regression guard under tags: there to
    #catch the retrain forgetting what lines mean, not to be maximised
    ev_a, ev_p, ev_n = [], [], []
    for num, name, anchor, pos, neg in TRIPLETS:
        ev_a.append(prefix + clean_line(anchor[1], anchor[0]))
        ev_p.append(prefix + clean_line(pos[1][0], pos[0]))
        ev_n.append(prefix + clean_line(neg[1][0], neg[0]))
    evaluator = TripletEvaluator(anchors=ev_a, positives=ev_p, negatives=ev_n, name="exam")

    #the number that decides the retrain: given a held out line and every
    #trainable tag, are the right tags in its top ten? computed here so a run
    #reports it as it goes, off the training file rather than a database
    tag_ir = None
    if args.objective in ("tags", "both"):
        held = load_jsonl("tag_testset.jsonl")
        tag_text = {r["positive"].split(":")[0]: r["positive"] for r in load_jsonl("train_tag_pairs.jsonl")}
        corpus = {slug: prefix + text for slug, text in tag_text.items()}
        queries, relevant = {}, {}
        for i, h in enumerate(held):
            gold = {t for t in h["tags"] if t in corpus}
            if not gold:
                continue
            queries["q" + str(i)] = prefix + h["line"]
            relevant["q" + str(i)] = gold
        if queries:
            tag_ir = InformationRetrievalEvaluator(
                queries=queries, corpus=corpus, relevant_docs=relevant,
                accuracy_at_k=[1, 10], precision_recall_at_k=[1, 10], map_at_k=[10],
                name="tags", show_progress_bar=False)
            print("tag retrieval evaluator: " + str(len(queries)) + " held out lines against "
                  + str(len(corpus)) + " tags")

    #a real run is hours on a gpu box, so --limit proves the wiring on a laptop
    if args.limit:
        train_sets = {k: v.select(range(min(args.limit, len(v)))) for k, v in train_sets.items()}
        print("LIMIT: " + str(args.limit) + " rows per dataset, this is a smoke test not a run")

    print("loading " + args.model + "...")
    model = SentenceTransformer(args.model, model_kwargs={"torch_dtype": torch.float32})
    print("exam before training:", evaluator(model))
    if tag_ir:
        print("tags before training:", tag_ir(model))

    #the base is usually already tuned, so the output is named for the objective
    #rather than stacking into mtg-tuned-mtg-tuned-embeddinggemma-300m
    stem = args.model.split("/")[-1]
    for old in ("mtg-tuned-", "mtg-tagtuned-"):
        if stem.startswith(old):
            stem = stem[len(old):]
    out_dir = os.path.join(HERE, "models", ("mtg-tagtuned-" if args.objective == "tags"
                                            else "mtg-tuned-") + stem)
    os.makedirs(os.path.dirname(out_dir), exist_ok=True)
    loss_mnrl = MultipleNegativesRankingLoss(model)
    loss_contrastive = ContrastiveLoss(model)
    for name in train_sets:
        losses[name] = loss_contrastive if name == "labeled" else loss_mnrl

    train_args = SentenceTransformerTrainingArguments(
        output_dir=out_dir + "-checkpoints",
        num_train_epochs=args.epochs,
        per_device_train_batch_size=batch,
        learning_rate=2e-5,
        #a float is a ratio, an int a literal step count: v5 folded warmup_ratio
        #into this argument so 0.1 is the first 10% of training, and v4 does not,
        #which is why requirements.txt pins the version
        warmup_steps=0.1,
        fp16=torch.cuda.is_available() and not is_gemma,  #T4 has no bf16, keep gemma in fp32
        eval_strategy="no",
        save_strategy="no",
        logging_steps=100,
        report_to=[],
        #LOAD BEARING for the tag objective. MultipleNegativesRanking treats
        #every other row's positive as this row's negative, which is wrong here:
        #the same line appears 4.3 times under different true tags and a batch of
        #64 expects three copies of activated-ability, so uncorrected the loss
        #pushes a line away from tags it has. NO_DUPLICATES bars a repeated value
        #in any column.
        #
        #it does not catch line A batched against a row whose positive is a
        #different tag A also carries. rarer (654 tags, batches of 16 to 64) but
        #still a false negative, maskable with the (line, tag) table from
        #train_tag_pairs.jsonl if a retrain ever plateaus on it
        batch_sampler=BatchSamplers.NO_DUPLICATES,
    )
    trainer = SentenceTransformerTrainer(
        model=model,
        args=train_args,
        train_dataset=train_sets,
        loss=losses,
    )
    trainer.train()

    print("exam after training:", evaluator(model))
    if tag_ir:
        print("tags after training:", tag_ir(model))
    model.save_pretrained(out_dir)
    print("\nsaved to " + out_dir)
    if args.objective == "lines":
        print("next: copy that folder into finetune/models/ on your machine, then add")
        print('  ("mtg-tuned", r"' + out_dir + '", ' + (('"' + prefix + '"') if prefix else "None") + "),")
        print("to MODELS in bakeoff_lines.py and rerun it for the real per-triplet exam.")
    else:
        print("next, in this order. leave EMBED_MODEL alone: swapping it overwrites the")
        print("live vectors in place, and they cannot be recovered without rerunning the")
        print("old model over the whole corpus. the second column exists for this.")
        print("")
        print("  1. upload to a new hugging face repo, from this same colab session")
        print("     before the runtime dies. the old repo is the rollback, so leave it:")
        print("       m = SentenceTransformer(r'" + out_dir + "')")
        print("       m.push_to_hub('you/mtg-tagtuned-embeddinggemma-300m', private=True)")
        print("  2. back on a machine with DATABASE_URL, fill the second column:")
        print("       python -m ingest.backfill_embeddings --model <the new repo> --index")
        print("     this leaves lines.embedding exactly as the site is serving it")
        print("  3. the real judge, against the same column:")
        print("       EMBED_COLUMN=embedding_v2 python -m finetune.exam_tags")
        print("     ship bar is recall @10 at 95%. the model in production sits at 47.0%,")
        print("     which is the centroid number, so compare like with like: the")
        print("     tags_cosine_recall@10 printed above is text retrieval and is not it")
        print("  4. python finetune/bakeoff_lines.py as a regression guard, not a target.")
        print("     a drop here is the umbrella tags teaching structure over meaning")
        print("  5. only if all that holds: EMBED_COLUMN=embedding_v2 on the web service")
        print("     to browse real searches. unset it to revert instantly")


if __name__ == "__main__":
    main()
