import numpy as np


def unit_rows(vecs):
    #a halfvec comes back up to 1.2e-4 off length 1, and the numpy passes read a
    #dot product as a cosine. web/app.py's UNIQUE_NOISE ties everything under
    #1e-6, so a line printed on two cards has to dot to 1 closer than that
    rows = np.asarray(vecs, dtype=np.float32)
    rows /= np.linalg.norm(rows, axis=1, keepdims=True)
    return rows
