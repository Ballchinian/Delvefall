#a linear probe per tag over the 768 dimension line vectors, the half of the
#autotags rule that reads a typed line directly rather than through its
#neighbours. labels are line_tags, so it learns what ingest/attribute.py says
#each line is about. over the copy freeze_tagdata.py writes:
#    python finetune/make_tagprobe.py --crossfit   the exam's predictions
#    python finetune/make_tagprobe.py              trained on every line
#
#--crossfit trains on one md5 half of the cards and predicts the other, so
#exam_autotags.py never scores a card the probe was taught on.
#
#weight decay 1e-5 underfits: list overlap 0.50 against 0.70 with none. tags on
#fewer than MIN_LINES training lines are left out, 1,699 tags at 2

import os
import sys
import time
import argparse

import numpy as np
import torch

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import exam_autotags as ea

MIN_LINES = 2
EPOCHS = 120
BATCH = 2048
LR = 1e-3
#unit vectors spread 1 over 768 dims, so each input is scaled back to about 1
SCALE = 768 ** 0.5
#kept per line in the crossfit file, far past the 10 chips a card can show
KEEP = 60


def train(x, labels, n_tags, seed):
    counts = np.zeros(n_tags, dtype=np.int64)
    for ts in labels:
        for t in ts:
            counts[t] += 1
    cols = np.flatnonzero(counts >= MIN_LINES)
    col_of = {int(t): k for k, t in enumerate(cols)}
    y = torch.zeros((len(labels), len(cols)))
    for r, ts in enumerate(labels):
        for t in ts:
            if t in col_of:
                y[r, col_of[t]] = 1
    torch.manual_seed(seed)
    lin = torch.nn.Linear(x.shape[1], len(cols))
    with torch.no_grad():
        prior = y.mean(0).clamp(1e-5, 1 - 1e-5)
        lin.bias.copy_(torch.log(prior / (1 - prior)))
        lin.weight.zero_()
    opt = torch.optim.Adam(lin.parameters(), lr=LR)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, EPOCHS)
    lossf = torch.nn.BCEWithLogitsLoss()
    t0 = time.time()
    for ep in range(EPOCHS):
        perm = torch.randperm(len(labels))
        total = 0.0
        for s in range(0, len(labels), BATCH):
            b = perm[s:s + BATCH]
            opt.zero_grad()
            loss = lossf(lin(x[b]), y[b])
            loss.backward()
            opt.step()
            total += loss.item() * len(b)
        sched.step()
        if ep % 20 == 0 or ep == EPOCHS - 1:
            print("  epoch %d loss %.5f  %.0fs" % (ep, total / len(labels), time.time() - t0))
    return cols, lin


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--crossfit", action="store_true")
    args = ap.parse_args()

    d = ea.Data()
    x = torch.from_numpy(d.emb) * SCALE
    labels = [d.line_tags.get(i, ()) for i in range(len(d.line_ids))]

    if not args.crossfit:
        print("training on all %d lines..." % len(labels))
        cols, lin = train(x, labels, len(d.tags), 0)
        np.savez(os.path.join(ea.DATA, "tagprobe.npz"), tags=np.array([d.tags[t] for t in cols]),
                 weight=lin.weight.detach().numpy() * SCALE, bias=lin.bias.detach().numpy())
        print("wrote tagprobe.npz, %d tags" % len(cols))
        return

    line_dev = np.array([d.half(int(c)) == "dev" for c in d.owner])
    idx = np.zeros((len(labels), KEEP), dtype=np.int16)
    prob = np.zeros((len(labels), KEEP), dtype=np.float16)
    for seed, taught in enumerate((line_dev, ~line_dev)):
        rows = np.flatnonzero(taught)
        print("training on %d lines, predicting the other half..." % len(rows))
        cols, lin = train(x[rows], [labels[i] for i in rows], len(d.tags), seed)
        other = np.flatnonzero(~taught)
        with torch.no_grad():
            for s in range(0, len(other), 4096):
                part = other[s:s + 4096]
                p = torch.sigmoid(lin(x[part])).numpy()
                top = np.argpartition(-p, KEEP, axis=1)[:, :KEEP]
                idx[part] = cols[top]
                prob[part] = np.take_along_axis(p, top, axis=1)
    np.savez(os.path.join(ea.DATA, "probe_crossfit.npz"), idx=idx, p=prob)
    print("wrote probe_crossfit.npz")


if __name__ == "__main__":
    main()
