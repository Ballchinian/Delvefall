#ranks models on "shown one line, does it put the right tags first".
#
#IN LEGACY BECAUSE THE QUESTION IT WAS BUILT FOR IS SETTLED. it asked which
#stock model to start the tag objective from, and EmbeddingGemma won that on
#lines already, so the answer was never in doubt and the run only confirmed it.
#the five stock models below are kept for the record, not because a rerun tells
#anyone anything.
#
#what it is FOR now, and why it is worth keeping: point MODELS at two trained
#models instead and it says which one is better at filing a line under the right
#tag. that is the tag half of what bakeoff_lines.py does for the line half, and
#it is the run to make when a second v2 model exists. there is only one today,
#so the comparison has nothing to sit beside.
#
#the v1 model cannot answer it. v1 was never taught what a tag slug says, so
#scoring it here measures a thing it was not trained for and reads as a loss
#that means nothing. exam_tags.py has the fair version of that comparison, the
#centroid scorer, which needs no model to know the vocabulary.
#
#no database, everything comes out of traindata. same held out cards and tag
#pool as exam_tags.py, so the numbers sit beside it.
#
#prompts are not cosmetic, embeddinggemma and bge scoring much lower bare, so
#each model gets the one it ships with and the prompt prints with the score

import os
import sys
import json
import argparse

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
#the tag objective's data lives in the live folder, one level up from legacy/
FINETUNE = os.path.dirname(HERE)
DATA_DIR = os.path.join(FINETUNE, "traindata")
sys.path.insert(0, FINETUNE)

#the five from the original bake-off, kept as the record of that run. to use
#this for its remaining purpose, replace them with two paths under
#finetune/models/ and read the table as new against old
MODELS = [
    "sentence-transformers/all-MiniLM-L6-v2",
    "BAAI/bge-small-en-v1.5",
    "Alibaba-NLP/gte-modernbert-base",
    "google/embeddinggemma-300m",
    "Qwen/Qwen3-Embedding-0.6B",
]

#recall @1, @5 and @10: of the tags a held out card really carries, the share
#the model puts in its top 1, top 5 and top 10 guesses. @10 is the headline,
#because a card carries a handful of tags and the picker shows more than one
KS = (1, 5, 10)


def load_pool():
    #make_training.py already applied the AUC and the review before writing
    #train_tag_pairs.jsonl, so reading it back needs neither tag_learnability.json nor
    #make_tagreview.py. that keeps this runnable from three data files and two
    #scripts, which matters when the whole lot has to reach a colab box
    text = {}
    for line in open(os.path.join(DATA_DIR, "train_tag_pairs.jsonl"), encoding="utf-8"):
        p = json.loads(line)["positive"]
        text[p.split(":")[0]] = p
    tags = sorted(text)
    held = [json.loads(l) for l in open(os.path.join(DATA_DIR, "tag_testset.jsonl"), encoding="utf-8")]
    rows, golds = [], []
    for h in held:
        gold = set(h["tags"]) & set(tags)
        if gold:
            rows.append(h["line"])
            golds.append(gold)
    return tags, [text[t] for t in tags], rows, golds


#some models ship a prompt NAME whose value is the empty string, which is not the
#same as shipping a prompt. bge-small does exactly that, so trusting the key
#scores it with no retrieval prefix while reporting that it used its own. these
#are the documented prefixes, used when the shipped value is blank
FALLBACK = {
    "BAAI/bge-small-en-v1.5": ("Represent this sentence for searching relevant passages: ", ""),
    "Qwen/Qwen3-Embedding-0.6B":
        ("Instruct: Given a line of Magic card rules text, retrieve the tags describing it\nQuery: ", ""),
}


def prompts_for(model, name):
    #the prompt STRINGS, not the names: an empty string is a missing prompt
    #wearing a name
    have = getattr(model, "prompts", None) or {}
    q = d = ""
    for key in ("query", "search_query", "Retrieval-query"):
        if have.get(key):
            q = have[key]
            break
    for key in ("document", "passage", "search_document", "Retrieval-document"):
        if have.get(key):
            d = have[key]
            break
    fq, fd = FALLBACK.get(name, ("", ""))
    return (q or fq), (d or fd)


def score(sims, golds, tags):
    ix = {t: i for i, t in enumerate(tags)}
    order = np.argsort(-sims, axis=1)
    rec = {k: 0.0 for k in KS}
    ap = 0.0
    for row, gold in enumerate(golds):
        ranked = [tags[i] for i in order[row]]
        for k in KS:
            rec[k] += len(set(ranked[:k]) & gold) / len(gold)
        hits = [i for i, t in enumerate(ranked) if t in gold]
        ap += sum((j + 1) / (r + 1) for j, r in enumerate(hits)) / len(gold)
    n = len(golds)
    return {"r1": rec[1] / n, "r5": rec[5] / n, "r10": rec[10] / n, "map": ap / n}


def main():
    ap_ = argparse.ArgumentParser()
    ap_.add_argument("--models", default=None, help="comma separated, defaults to the bake-off five")
    ap_.add_argument("--batch", type=int, default=32)
    args = ap_.parse_args()
    names = args.models.split(",") if args.models else MODELS

    tags, tag_texts, lines, golds = load_pool()
    print(str(len(lines)) + " held out lines, " + str(len(tags)) + " tags to rank\n")

    import torch
    from sentence_transformers import SentenceTransformer

    results = []
    for name in names:
        print("=" * 70)
        print(name)
        try:
            model = SentenceTransformer(name, model_kwargs={"torch_dtype": torch.float32},
                                        trust_remote_code=True)
        except Exception as e:
            print("  could not load: " + str(e)[:120])
            continue
        q, d = prompts_for(model, name)
        dims = model.get_sentence_embedding_dimension()
        print("  dims: " + str(dims))
        print("  query prompt:    " + (repr(q[:60]) if q else "(none)"))
        print("  document prompt: " + (repr(d[:60]) if d else "(none)"))
        L = model.encode(lines, batch_size=args.batch, normalize_embeddings=True,
                         show_progress_bar=False, prompt=q or None)
        T = model.encode(tag_texts, batch_size=args.batch, normalize_embeddings=True,
                         show_progress_bar=False, prompt=d or None)
        r = score(np.asarray(L, dtype=np.float32) @ np.asarray(T, dtype=np.float32).T, golds, tags)
        r["name"] = name
        r["dims"] = dims
        r["prompt"] = "yes" if (q or d) else "none"
        results.append(r)
        print("  recall @1 %5.1f%%   @5 %5.1f%%   @10 %5.1f%%   MAP %5.1f%%"
              % (100 * r["r1"], 100 * r["r5"], 100 * r["r10"], 100 * r["map"]))
        del model
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    print("\n" + "=" * 70)
    print("BASE MODELS ON THE TAG OBJECTIVE, best recall @10 first")
    print("%-42s %7s %7s %6s %7s" % ("model", "r@10", "MAP", "dims", "prompt"))
    for r in sorted(results, key=lambda x: -x["r10"]):
        print("%-42s %6.1f%% %6.1f%% %6d %7s"
              % (r["name"][:42], 100 * r["r10"], 100 * r["map"], r["dims"], r["prompt"]))
    print("\nzero shot only, and read it with two caveats. a model that starts")
    print("higher need not finish higher: capacity to absorb 36k pairs is a")
    print("different thing from what it already knows. and dims is a real")
    print("constraint, not trivia: lines.embedding is vector(768), so anything")
    print("of another width needs EMBED_DIMS and the column type changed too.")


if __name__ == "__main__":
    main()
