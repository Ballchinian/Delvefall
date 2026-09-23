#/admin is the only page that wakes the model service, and parity waits up to
#BUDGET (90s) for a sleeping container. the wake has to happen with no pooled
#connection in hand: a transaction held open on lines for that long is what an
#ingest queues behind, and every search queues behind the ingest. that is the
#09-22 outage reached from a page only Ethan opens.
#
#the structural test is the one that matters. the split reads correctly today and
#the next edit to the route is what would undo it

import ast
import os

import numpy as np
import pytest

import embedder
from conftest import ROOT


def admin_route():
    with open(os.path.join(ROOT, "web", "app.py"), encoding="utf-8") as f:
        tree = ast.parse(f.read())
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "admin":
            return node
    raise AssertionError("web/app.py has no admin route to check")


def pool_blocks(fn):
    return [n for n in ast.walk(fn) if isinstance(n, ast.With)
            and any("pool.connection" in ast.unparse(i.context_expr) for i in n.items)]


def calls(node):
    return [ast.unparse(n.func) for n in ast.walk(node) if isinstance(n, ast.Call)]


class _Stored:
    #pgvector hands back its own Vector, and HalfVector since the rebuild. both
    #answer to_numpy(), and np.asarray of either raises rather than converting
    def __init__(self, values):
        self.values = np.array(values, dtype=np.float32)

    def to_numpy(self):
        return self.values


class TestTheAdminWakeHoldsNoPooledConnection:

    def test_the_wake_is_outside_every_pool_block(self):
        fn = admin_route()
        assert "embedder.parity" in calls(fn), "the parity guard is gone from /admin"
        for block in pool_blocks(fn):
            assert "embedder.parity" not in calls(block), \
                "the wake is back inside a borrowed connection, and 90s of it"

    def test_the_sample_is_still_read_on_one(self):
        #the other half of the same claim: the read needs the connection, so a
        #split that moved BOTH halves out would be a different bug, not a fix
        fn = admin_route()
        blocks = pool_blocks(fn)
        assert blocks, "/admin borrows no connection at all now"
        assert any("embedder.parity_rows" in calls(b) for b in blocks), \
            "the parity sample is not read on the pooled connection"


class TestParityWorksFromRowsAlone:

    def test_it_compares_without_a_connection(self, monkeypatch):
        monkeypatch.setattr(embedder, "EMBED_URL", "http://embed.test")
        monkeypatch.setattr(embedder, "embed",
                            lambda texts: [np.array([0.6, 0.8], dtype=np.float32)])
        got = embedder.parity([{"line_text": "Flying", "embedding": _Stored([0.6, 0.8])}])
        assert got["ok"]
        assert got["lines"] == 1
        assert got["worst"] == pytest.approx(1.0, abs=1e-6)

    def test_a_service_on_other_weights_shows_as_a_worse_cosine(self, monkeypatch):
        #the whole point of the guard: the numbers on /custom are comparisons
        #against the stored vectors, so drift has to be visible here
        monkeypatch.setattr(embedder, "EMBED_URL", "http://embed.test")
        monkeypatch.setattr(embedder, "embed",
                            lambda texts: [np.array([1.0, 0.0], dtype=np.float32)])
        got = embedder.parity([{"line_text": "Flying", "embedding": _Stored([0.6, 0.8])}])
        assert got["worst"] == pytest.approx(0.6, abs=1e-6)

    def test_a_stored_vector_off_length_one_still_reads_as_agreement(self, monkeypatch):
        #a halfvec comes back up to 1.2e-4 off length 1, so both sides are
        #renormalised before the dot. short of that, the same direction reads as
        #drift: 0.9988 here, which would fail the 0.999999 bar on its own
        monkeypatch.setattr(embedder, "EMBED_URL", "http://embed.test")
        monkeypatch.setattr(embedder, "embed",
                            lambda texts: [np.array([0.6, 0.8], dtype=np.float32)])
        short = _Stored([0.6 * 0.9988, 0.8 * 0.9988])
        got = embedder.parity([{"line_text": "Flying", "embedding": short}])
        assert got["worst"] == pytest.approx(1.0, abs=1e-6)

    def test_no_rows_never_wakes_anything(self, monkeypatch):
        monkeypatch.setattr(embedder, "EMBED_URL", "http://embed.test")

        def refuse(texts):
            raise AssertionError("woke the service with nothing to compare against")

        monkeypatch.setattr(embedder, "embed", refuse)
        assert embedder.parity([])["why"] == "no lines to compare against"

    def test_no_service_says_so_and_not_that_the_table_is_empty(self, monkeypatch):
        #parity_rows returns [] when EMBED_URL is unset, so the order of the two
        #checks below it is what decides whether the page blames the table
        monkeypatch.setattr(embedder, "EMBED_URL", "")
        assert embedder.parity([])["why"] == "EMBED_URL is not set"


class TestParityRowsAsksForNothingItCannotUse:

    def test_no_service_means_no_query(self, monkeypatch):
        #ORDER BY random() is a seq scan of the 385mb lines table, and with no
        #service to compare against it buys nothing
        class Loud:
            def execute(self, *args, **kwargs):
                raise AssertionError("scanned lines with no service to ask")

        monkeypatch.setattr(embedder, "EMBED_URL", "")
        assert embedder.parity_rows(Loud()) == []

    def test_it_asks_for_the_sample_size_it_was_given(self, monkeypatch):
        seen = {}

        class Fake:
            def execute(self, sql, args):
                seen["sql"] = sql
                seen["args"] = args
                return self

            def fetchall(self):
                return [{"line_text": "Flying", "embedding": _Stored([1.0, 0.0])}]

        monkeypatch.setattr(embedder, "EMBED_URL", "http://embed.test")
        rows = embedder.parity_rows(Fake(), how_many=7)
        assert len(rows) == 1
        assert seen["args"] == (7,)
        #whole-card rows are a different kind of text and would read as drift
        assert "NOT whole" in seen["sql"]
