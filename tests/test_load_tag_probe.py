#tools/load_tag_probe.py stamps tag_probe with the weights the probe was trained
#against, and /custom shows chips only while that stamp matches the weights that
#made the vectors. the stamp comes out of the npz, so an npz that cannot say, or
#says other weights, must never be loaded

import os
import sys

import numpy as np
import pytest

from conftest import ROOT, needs_db

sys.path.insert(0, os.path.join(ROOT, "tools"))

#for the driver, not the rows: the tool imports psycopg at the top, which the
#pure suite must not
pytestmark = needs_db

WEIGHTS = "d06f255a" + "0" * 56
RETRAIN = "e17a3c90" + "0" * 56


def npz(tmp_path, **trained):
    #the arrays finetune/make_tagprobe.py saves, the model and sha256 as it writes them
    path = tmp_path / "tagprobe.npz"
    np.savez(path, tags=np.array(["draw-on-attack"]), weight=np.zeros((1, 768)), bias=np.zeros(1),
             **{k: np.array(v) for k, v in trained.items()})
    return str(path)


class TestWhatAProbeSaysItWasTrainedOn:

    def test_the_model_and_weights_come_back_as_text(self, tmp_path):
        #np.savez keeps a str as a 0-d array, and the stamp has to be the plain text
        #probe_stale compares against embed_sha256
        from load_tag_probe import read_probe
        got = read_probe(npz(tmp_path, model="test/model-a", sha256=WEIGHTS))[3]
        assert got == ("test/model-a", WEIGHTS)

    def test_a_probe_that_records_nothing_says_nothing(self, tmp_path):
        from load_tag_probe import read_probe
        assert read_probe(npz(tmp_path))[3] == (None, None)


class TestWhichProbesLoad:

    def test_the_same_weights_load(self):
        from load_tag_probe import mismatch
        assert mismatch(WEIGHTS, WEIGHTS) == ""

    def test_a_probe_trained_on_other_weights_is_refused_and_says_retrain(self):
        from load_tag_probe import mismatch
        #loading the same npz again would stamp the same old weights, so the way
        #out is a new probe
        why = mismatch(WEIGHTS, RETRAIN)
        assert WEIGHTS[:12] in why and RETRAIN[:12] in why
        assert "retrain" in why

    @pytest.mark.parametrize("trained,weights", [(None, WEIGHTS), (WEIGHTS, None)])
    def test_either_side_unknown_is_refused(self, trained, weights):
        from load_tag_probe import mismatch
        assert mismatch(trained, weights)
