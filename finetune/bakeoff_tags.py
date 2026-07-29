#which base model starts highest on the line -> tag objective, before any fine
#tuning. bakeoff_lines.py asks a different question and picked EmbeddingGemma
#for it; the objective changed, so the base is remeasured rather than
#inherited. good at paraphrase does not mean good at "what is this line about".
#
#from the repo root, no database, everything comes out of traindata:
#    python finetune/bakeoff_tags.py
#same held out cards and tag pool as exam_tags.py, so the numbers sit beside it.
#
#this is the TEXT scorer: lines ranked against each tag's words
#("slug: description"), which is what training optimises. not comparable to
#exam_tags.py's centroid headline, since the production model was never taught
#what a slug says and text retrieval would flatter a stock model against it.
#compare bases with bases.
#
#prompts are not cosmetic: embeddinggemma and bge score much lower bare, so each
#model is given the one it ships with. the prompt is printed with the score.

import os
import sys
import json
import argparse

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "traindata")
sys.path.insert(0, HERE)

#the five from the original bake-off, plus the tuned model when it is reachable.
#all of these were already pulled once for that bake-off, so a rerun is offline
MODELS = [
    "sentence-transformers/all-MiniLM-L6-v2",
    "BAAI/bge-small-en-v1.5",
    "Alibaba-NLP/gte-modernbert-base",
    "google/embeddinggemma-300m",
    "Qwen/Qwen3-Embedding-0.6B",
]

KS = (1, 5, 10)


def load_pool():
    #the trainable pool IS whatever train_tags.jsonl contains: make_training.py
    #already applied the AUC and the review before writing it, so reading the
    #file back needs neither tag_learnability.json nor make_tagreview.py. that
    #keeps this runnable from three data files and two scripts, which matters
    #when the whole lot has to reach a colab box
    text = {}
    for line in open(os.path.join(DATA_DIR, "train_tags.jsonl"), encoding="utf-8"):
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


#some models ship a prompt name whose VALUE is the empty string, which is not
#the same as shipping a prompt. bge-small does exactly that, and taking the key
#at face value scored it with no retrieval prefix at all while reporting that
#it had used its own. these are the documented prefixes for the models that
#want one, used when the shipped value is blank
FALLBACK = {
    "BAAI/bge-small-en-v1.5": ("Represent this sentence for searching relevant passages: ", ""),
    "Qwen/Qwen3-Embedding-0.6B":
        ("Instruct: Given a line of Magic card rules text, retrieve the tags describing it\nQuery: ", ""),
}


def prompts_for(model, name):
    #the real prompt STRINGS, not just the names, because an empty string is a
    #missing prompt wearing a name
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
    print("\nZERO SHOT ONLY, and read it with two caveats. a model that starts")
    print("higher need not finish higher: capacity to absorb 36k pairs is a")
    print("different thing from what it already knows. and DIMS is a real")
    print("constraint, not trivia: lines.embedding is vector(768), so anything")
    print("of another width needs EMBED_DIMS and the column type changed too.")


if __name__ == "__main__":
    main()
