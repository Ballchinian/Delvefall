#embed/fetch_model.py is where both halves of the site get their weights: the
#daily ingest unpacks the release on a github runner, and the model service's
#image is built from the same tar, so a card has to read the same percent on
#both.
#
#the failure it has to survive is a body that arrives short and raises nothing.
#python's http client returns what it got, so a cut download only shows up as a
#sha256 mismatch, which reads like a replaced asset and stopped a run here on
#2026-09-22 on the one thing a retry fixes

import hashlib
import importlib.util
import os

import pytest

from conftest import ROOT

#by path, because embed/ has no __init__.py: railway builds that folder as a
#docker context of its own. the script is stdlib only, so it loads anywhere
_spec = importlib.util.spec_from_file_location(
    "fetch_model", os.path.join(ROOT, "embed", "fetch_model.py"))
fetch_model = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fetch_model)

WHOLE = b"the weights, every byte of them" * 64
SHORT = WHOLE[:100]


class Body:
    #enough of an http response for the read loop and no more

    def __init__(self, data):
        self.data = data

    def read(self, n):
        out, self.data = self.data[:n], self.data[n:]
        return out

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture
def no_waiting(monkeypatch):
    #the retry sleeps 5s, which is right in a workflow and pointless here
    monkeypatch.setattr(fetch_model.time, "sleep", lambda seconds: None)


def serve(monkeypatch, bodies):
    #one body per try, so each test says what every attempt gets back
    tries = []

    def urlopen(url, timeout=None):
        tries.append(url)
        body = bodies[len(tries) - 1]
        if isinstance(body, Exception):
            raise body
        return Body(body)

    monkeypatch.setattr(fetch_model.urllib.request, "urlopen", urlopen)
    return tries


class TestABodyThatArrivesShort:

    def test_it_is_fetched_again(self, tmp_path, monkeypatch, no_waiting):
        tries = serve(monkeypatch, [SHORT, WHOLE])
        path = tmp_path / "model.tar"
        got = fetch_model.download("https://example.invalid/model.tar", str(path), len(WHOLE))
        assert got == hashlib.sha256(WHOLE).hexdigest()
        assert path.read_bytes() == WHOLE
        assert len(tries) == 2

    def test_running_out_of_tries_says_how_short(self, tmp_path, monkeypatch, no_waiting):
        tries = serve(monkeypatch, [SHORT, SHORT, SHORT])
        with pytest.raises(SystemExit) as stop:
            fetch_model.download("https://example.invalid/model.tar",
                                 str(tmp_path / "model.tar"), len(WHOLE))
        assert str(len(SHORT)) in str(stop.value)
        assert str(len(WHOLE)) in str(stop.value)
        assert len(tries) == 3


class TestABodyThatArrivesWhole:

    def test_it_is_not_fetched_twice(self, tmp_path, monkeypatch, no_waiting):
        tries = serve(monkeypatch, [WHOLE])
        got = fetch_model.download("https://example.invalid/model.tar",
                                   str(tmp_path / "model.tar"), len(WHOLE))
        assert got == hashlib.sha256(WHOLE).hexdigest()
        assert len(tries) == 1


class TestAConnectionThatRefuses:

    def test_it_still_spends_the_tries_and_then_raises(self, tmp_path, monkeypatch, no_waiting):
        #the older half of the retry, next door to the new one: a body that never
        #starts raises, a body that stops half way does not
        error = fetch_model.urllib.error.URLError("connection reset")
        tries = serve(monkeypatch, [error, error, error])
        with pytest.raises(fetch_model.urllib.error.URLError):
            fetch_model.download("https://example.invalid/model.tar",
                                 str(tmp_path / "model.tar"), len(WHOLE))
        assert len(tries) == 3

    def test_one_refusal_is_not_the_end_of_it(self, tmp_path, monkeypatch, no_waiting):
        tries = serve(monkeypatch, [fetch_model.urllib.error.URLError("connection reset"), WHOLE])
        got = fetch_model.download("https://example.invalid/model.tar",
                                   str(tmp_path / "model.tar"), len(WHOLE))
        assert got == hashlib.sha256(WHOLE).hexdigest()
        assert len(tries) == 2
