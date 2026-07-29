#neighborhood sanity check: embeds every line in the site database with the
#tuned model and the live model, then shows the top matches for a spread of
#ordinary probe searches side by side. the exam is only 26 questions, this
#is how everything else gets eyeballed before trusting a model.
#
#run from the repo root, writes finetune/legacy/sanity_report.txt beside itself

import os
import sys
import numpy as np

#two hops out of legacy/: the finetune folder for the sibling import of
#make_training, and the repo root for common/
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from make_training import find_db_url, load_lines_from_db

HERE = os.path.dirname(os.path.abspath(__file__))
#the model sits in finetune/models/, one level up from this script and then down
FINETUNE = os.path.dirname(HERE)
PREFIX = "task: sentence similarity | query: "

MODELS = [
    ("mtg-tuned EmbeddingGemma", os.path.join(FINETUNE, "models", "mtg-tuned-embeddinggemma-300m"), PREFIX),
    ("current all-MiniLM-L6-v2", "sentence-transformers/all-MiniLM-L6-v2", None),
]

#a spread of ordinary searches: removal, counters, draw, ramp, keywords,
#lifegain, bounce, reanimation, discard, burn, looting, wipes
PROBES = [
    "Destroy target creature.",
    "Destroy all creatures.",
    "Counter target spell.",
    "Draw two cards.",
    "{T}: Add one mana of any color.",
    "Search your library for a basic land card, put that card onto the battlefield tapped, then shuffle.",
    "Flying",
    "Hexproof",
    "When this creature enters, you gain 3 life.",
    "Return target creature to its owner's hand.",
    "Return target creature card from your graveyard to the battlefield.",
    "Target player discards two cards.",
    "this card deals 3 damage to any target.",
    "{T}: Draw a card, then discard a card.",
]

TOP = 8


def main():
    from sentence_transformers import SentenceTransformer
    import torch

    print("reading lines from the site database...")
    lines = load_lines_from_db(find_db_url())
    print(str(len(lines)) + " lines")

    report = []
    results = {}
    for label, model_id, prefix in MODELS:
        print("embedding everything with " + label + " (the slow part)...")
        model = SentenceTransformer(model_id, device="cpu", model_kwargs={"torch_dtype": torch.float32})
        texts = [(prefix or "") + l for l in lines]
        embs = model.encode(texts, batch_size=64, normalize_embeddings=True,
                            convert_to_numpy=True, show_progress_bar=True)
        probe_embs = model.encode([(prefix or "") + p for p in PROBES], batch_size=16,
                                  normalize_embeddings=True, convert_to_numpy=True)
        sims = probe_embs @ embs.T  #probes x lines
        results[label] = sims
        del model, embs

    for pi, probe in enumerate(PROBES):
        report.append("")
        report.append("=" * 100)
        report.append("PROBE: " + probe)
        for label, model_id, prefix in MODELS:
            sims = results[label][pi]
            order = np.argsort(-sims)
            report.append("  --- " + label + " ---")
            shown = 0
            for idx in order:
                if lines[idx] == probe:
                    continue  #the line itself is not interesting
                report.append("  %5.1f%%  %s" % (sims[idx] * 100, lines[idx][:100]))
                shown += 1
                if shown >= TOP:
                    break

    text = "\n".join(report)
    out = os.path.join(HERE, "sanity_report.txt")
    with open(out, "w", encoding="utf-8") as f:
        f.write(text)
    print(text)
    print("\nreport written to " + out)


if __name__ == "__main__":
    main()
