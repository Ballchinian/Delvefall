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
import io
import os
import tarfile

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


def tar_of(**members):
    #an uncompressed tar, the release's format, holding these names and bytes
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w") as tar:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return out.getvalue()


@pytest.fixture
def released(monkeypatch, no_waiting):
    #fetch() against a release that serves `body`, its sha256 and size in step so
    #the download is accepted and what happens next is what is under test
    def serve_release(body):
        monkeypatch.setattr(fetch_model, "release", lambda: {
            "sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body), "file": "model.tar",
            "tag": "model-test", "url": "https://example.invalid/model.tar"})
        return serve(monkeypatch, [body])

    return serve_release


def old_model(dest):
    dest.mkdir()
    (dest / "old.bin").write_bytes(b"the release before")
    (dest / ".sha256").write_text("0" * 64 + "\n")


class TestWhereTheModelGoes:

    def test_a_folder_it_did_not_fill_is_refused_before_the_download(self, tmp_path, released):
        #every file in dest is replaced, so --dest . from the repo root took .git
        #with it
        tries = released(tar_of(**{"model.safetensors": b"weights"}))
        dest = tmp_path / "repo"
        dest.mkdir()
        (dest / "HEAD").write_text("ref: refs/heads/main")
        with pytest.raises(SystemExit, match="no .sha256"):
            fetch_model.fetch(str(dest))
        assert (dest / "HEAD").exists()
        assert tries == []

    def test_a_new_release_replaces_the_old_one_whole(self, tmp_path, released):
        body = tar_of(**{"model.safetensors": b"weights"})
        released(body)
        dest = tmp_path / "model"
        old_model(dest)
        fetch_model.fetch(str(dest))
        assert sorted(os.listdir(dest)) == [".sha256", "model.safetensors"]
        assert (dest / ".sha256").read_text().strip() == hashlib.sha256(body).hexdigest()
        #and nothing of the swap is left beside it
        assert os.listdir(tmp_path) == ["model"]

    def test_a_failed_extract_leaves_the_old_model_and_its_stamp(self, tmp_path, released):
        #the right bytes that are not a tar: the old model is still whole, and its
        #stamp still says which one it is
        released(b"not a tar at all" * 64)
        dest = tmp_path / "model"
        old_model(dest)
        with pytest.raises(tarfile.ReadError):
            fetch_model.fetch(str(dest))
        assert sorted(os.listdir(dest)) == [".sha256", "old.bin"]
        assert (dest / ".sha256").read_text().strip() == "0" * 64

    def test_a_tar_reaching_out_of_the_folder_is_refused_and_stamps_nothing(self, tmp_path, released):
        #filter="data" is what stops it, and no stamp may say a model is there
        released(tar_of(**{"../escaped.txt": b"outside"}))
        dest = tmp_path / "model"
        with pytest.raises(tarfile.FilterError):
            fetch_model.fetch(str(dest))
        assert not (tmp_path / "escaped.txt").exists()
        assert not (dest / ".sha256").exists()

