#scores candidate embedding models against the hand built triplet list in
#bakeoff_lines.md. a triplet passes when the anchor line lands closer to the
#should-match card than to the should-not card, each candidate card's BEST
#matching line counting, same as the real engine.

import os
import sys
import csv
import gc

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from common.cards import clean_line

#(label, huggingface id, prompt prepended to every line or None)
#embeddinggemma and qwen3 are trained to expect a task prompt, the others not
MODELS = [
    ("all-MiniLM-L6-v2 (current)", "sentence-transformers/all-MiniLM-L6-v2", None),
    ("bge-small-en-v1.5", "BAAI/bge-small-en-v1.5", None),
    ("gte-modernbert-base", "Alibaba-NLP/gte-modernbert-base", None),
    ("EmbeddingGemma-300m", "google/embeddinggemma-300m", "task: sentence similarity | query: "),
    ("Qwen3-Embedding-0.6B", "Qwen/Qwen3-Embedding-0.6B", "Instruct: Retrieve semantically similar text.\nQuery: "),
    #trained by finetune/train.py. it learned with the sentence similarity
    #prompt, so it must always be used with the same one
    ("mtg-tuned EmbeddingGemma", os.path.join(os.path.dirname(os.path.abspath(__file__)), "models", "mtg-tuned-embeddinggemma-300m"),
     "task: sentence similarity | query: "),
]

#both invocation styles work: -m puts the repo root on the path, a direct path
#puts only finetune/ there, and examfile has to be importable either way
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import examfile


#the exam itself lives in testing_list/bakeoff_lines.md, so the file people edit
#is the file that scores. a candidate card carries every line the engine would
#see for it and its best matching one counts, which is why the file joins those
#lines with + rather than quoting only the interesting one
def _load():
    out = []
    for i, e in enumerate(examfile.read("bakeoff_lines")["Triplets"], 1):
        f = e["fields"]
        anchor, lines = examfile.card_lines(f["Anchor"])
        out.append((i, f["Test"], (anchor, lines[0]),
                    examfile.card_lines(f["Match"]), examfile.card_lines(f["NOT"])))
    return out


TRIPLETS = _load()


def cleaned(card_name, line):
    out = clean_line(line, card_name)
    if not out:
        raise ValueError("line cleaned away to nothing: " + card_name + " / " + line)
    return out


def run_model(label, model_id, prompt):
    from sentence_transformers import SentenceTransformer
    import torch

    print("")
    print("== " + label + " ==")
    print("loading " + model_id + " (downloads on first run)...")
    model = SentenceTransformer(model_id, device="cpu",
                                model_kwargs={"torch_dtype": torch.float32})

    #every unique cleaned line embeds once
    texts = []
    for num, name, anchor, pos, neg in TRIPLETS:
        texts.append(cleaned(anchor[0], anchor[1]))
        for line in pos[1]:
            texts.append(cleaned(pos[0], line))
        for line in neg[1]:
            texts.append(cleaned(neg[0], line))
    uniq = sorted(set(texts))
    kwargs = {"batch_size": 16, "normalize_embeddings": True, "convert_to_numpy": True}
    if prompt:
        kwargs["prompt"] = prompt
    embs = model.encode(uniq, **kwargs)
    vec = {}
    for i, t in enumerate(uniq):
        vec[t] = embs[i]

    results = []
    passes = 0
    for num, name, anchor, pos, neg in TRIPLETS:
        a = vec[cleaned(anchor[0], anchor[1])]
        best_pos = max(float(a @ vec[cleaned(pos[0], line)]) for line in pos[1])
        best_neg = max(float(a @ vec[cleaned(neg[0], line)]) for line in neg[1])
        ok = best_pos > best_neg
        if ok:
            passes += 1
        margin = best_pos - best_neg
        print(("%2d %-28s %s  match %5.1f%%  not %5.1f%%  (%+.1f)")
              % (num, name, "PASS" if ok else "FAIL", best_pos * 100, best_neg * 100, margin * 100))
        results.append((num, name, best_pos, best_neg, ok))

    print("score: " + str(passes) + "/" + str(len(TRIPLETS)))

    del model
    gc.collect()
    return passes, results


def main():
    scoreboard = []
    rows = []
    for label, model_id, prompt in MODELS:
        try:
            passes, results = run_model(label, model_id, prompt)
        except Exception as e:
            msg = str(e).replace("\n", " ")[:200]
            print("")
            print("== " + label + " ==")
            print("SKIPPED: " + msg)
            if "gated" in msg.lower() or "401" in msg or "403" in msg:
                print("(this repo is gated: accept the license on huggingface.co/" + model_id)
                print(" then run: huggingface-cli login)")
            scoreboard.append((label, None))
            continue
        scoreboard.append((label, passes))
        for num, name, best_pos, best_neg, ok in results:
            rows.append([label, num, name, round(best_pos, 4), round(best_neg, 4), "pass" if ok else "fail"])

    out_path = os.path.join(os.path.dirname(__file__), "out", "bakeoff_results.csv")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["model", "triplet", "label", "best_match_sim", "best_not_sim", "result"])
        w.writerows(rows)

    print("")
    print("==== scoreboard ====")
    for label, passes in scoreboard:
        if passes is None:
            print("%-30s skipped" % label)
        else:
            print("%-30s %d/%d" % (label, passes, len(TRIPLETS)))
    print("")
    print("details written to " + out_path)


if __name__ == "__main__":
    main()
