#downloads the embedding weights from the github release named in
#model_release.json and unpacks them into --dest.
#
#STDLIB ONLY, deliberately: the Dockerfile runs it before pip has installed
#anything, and the ingest workflow runs it without adding a dependency to
#ingest/requirements.txt. nothing here imports torch.
#
#both runners call this and get byte identical weights, which is the whole
#point: github actions embeds the table every morning and railway embeds what a
#visitor types, and a card that reads 0% original has to read 0% on both.
#
#    python embed/fetch_model.py --dest /model
#
#a second call with the weights already there and the hash matching does
#nothing, so the ingest can call it on every run and a warm cache costs a
#stat() rather than 1.25gb.

import os
import sys
import json
import time
import shutil
import hashlib
import tarfile
import argparse
import tempfile
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
RELEASE = os.path.join(HERE, "model_release.json")

#read in chunks rather than whole: the tar is about 1.25gb and railway's build
#container is not sized for holding it in memory as well as on disk
CHUNK = 1 << 20


def release():
    with open(RELEASE, encoding="utf-8") as f:
        return json.load(f)


def stamp_path(dest):
    return os.path.join(dest, ".sha256")


def already_there(dest, sha256):
    #the stamp is written LAST, after the extract finished, so its presence
    #means a whole model and not a half unpacked one
    try:
        with open(stamp_path(dest), encoding="utf-8") as f:
            return f.read().strip() == sha256
    except OSError:
        return False


def download(url, path, tries=3):
    #the release asset is a redirect to objects.githubusercontent.com, which
    #urlopen follows. no token: the repo is public, and needing one here would
    #have been the reason not to use a release asset at all
    for attempt in range(tries):
        digest = hashlib.sha256()
        try:
            with urllib.request.urlopen(url, timeout=60) as r, open(path, "wb") as out:
                while True:
                    chunk = r.read(CHUNK)
                    if not chunk:
                        break
                    digest.update(chunk)
                    out.write(chunk)
            return digest.hexdigest()
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            if attempt == tries - 1:
                raise
            print("  download failed (" + str(e) + "), retrying in 5s")
            time.sleep(5)


def fetch(dest, force=False):
    rel = release()
    sha256 = rel["sha256"]
    if not force and already_there(dest, sha256):
        print("model already at " + dest + " (" + sha256[:12] + "), nothing to do")
        return dest

    os.makedirs(dest, exist_ok=True)
    #the temp file sits beside dest rather than in /tmp, which on railway's
    #builder is a small tmpfs that 1.25gb does not fit in
    holding = tempfile.mkdtemp(prefix=".fetch-", dir=os.path.dirname(os.path.abspath(dest)) or ".")
    tar_path = os.path.join(holding, "model.tar")
    try:
        print("downloading " + rel["file"] + " from " + rel["tag"] + "...")
        got = download(rel["url"], tar_path)
        if got != sha256:
            raise SystemExit("sha256 mismatch: model_release.json says " + sha256 +
                             ", the download is " + got + ". the release asset was replaced, "
                             "or the download truncated")
        print("  sha256 ok, extracting...")
        #anything already in dest is from an older release, and leaving it would
        #mix two models in one folder
        for name in os.listdir(dest):
            path = os.path.join(dest, name)
            shutil.rmtree(path) if os.path.isdir(path) else os.remove(path)
        with tarfile.open(tar_path, "r:") as tar:
            #filter="data" refuses absolute paths, "..", links out of the tree
            #and device files. the tar is ours, but an extract that trusts its
            #input is a foothold in an image that also holds nothing else
            tar.extractall(dest, filter="data")
    finally:
        shutil.rmtree(holding, ignore_errors=True)

    with open(stamp_path(dest), "w", encoding="utf-8") as f:
        f.write(sha256 + "\n")
    print("model ready at " + dest)
    return dest


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dest", required=True, help="folder to unpack the weights into")
    ap.add_argument("--force", action="store_true", help="fetch again even if the hash matches")
    args = ap.parse_args()
    fetch(args.dest, force=args.force)


if __name__ == "__main__":
    sys.exit(main())
