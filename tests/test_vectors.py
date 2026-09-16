#lines.embedding is a halfvec, so every vector the ingest reads back has each
#component rounded to ieee half precision. the numpy passes dot rows together
#and read the result as a cosine, which only holds for rows of length 1

import numpy as np

import app
from common.vectors import unit_rows


class TestAHalfPrecisionRowIsUnitLengthAgain:

    def test_a_line_printed_on_two_cards_still_ties_at_zero(self):
        #uniqueness is 1 minus a line's best dot product against other cards, and
        #/unique ties every card under app.UNIQUE_NOISE as "other cards already do
        #everything it does". two cards printing the same text hold the same
        #vector, so that dot product is the row against itself. unrenormalised,
        #the rounding put the live vectors up to 1.2e-4 off, and 2,708 of the
        #4,392 tied cards fell out of the tie
        rng = np.random.default_rng(7)
        v = rng.standard_normal((500, 768)).astype(np.float32)
        v /= np.linalg.norm(v, axis=1, keepdims=True)
        rows = unit_rows(v.astype(np.float16))
        assert (1 - (rows * rows).sum(axis=1)).max() < app.UNIQUE_NOISE
