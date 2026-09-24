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


def download(url, path, size, tries=3):
    #the release asset is a redirect to objects.githubusercontent.com, which
    #urlopen follows. no token: the repo is public, and needing one here would
    #have been the reason not to use a release asset at all
    for attempt in range(tries):
        digest = hashlib.sha256()
        got = 0
        try:
            with urllib.request.urlopen(url, timeout=60) as r, open(path, "wb") as out:
                while True:
                    chunk = r.read(CHUNK)
                    if not chunk:
                        break
                    digest.update(chunk)
                    got += len(chunk)
                    out.write(chunk)
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            if attempt == tries - 1:
                raise
            print("  download failed (" + str(e) + "), retrying in 5s")
            time.sleep(5)
            continue
        if got == size:
            return digest.hexdigest()
        #a cut connection is not an exception: read() returns b"" and raises
        #nothing, so a short body reaches the sha256 check as a mismatch, which
        #reads like a replaced release asset and stops the run on the one thing
        #a retry fixes. it happened here on 09-22, hence the byte count
        if attempt == tries - 1:
            raise SystemExit("the download stopped at " + str(got) + " bytes of " + str(size) +
                             ", " + str(tries) + " times over. the network cut it, and nothing "
                             "here can tell that from a release asset that shrank")
        print("  got " + str(got) + " of " + str(size) + " bytes, retrying in 5s")
        time.sleep(5)


def fetch(dest, force=False):
    rel = release()
    sha256 = rel["sha256"]
    if not force and already_there(dest, sha256):
        print("model already at " + dest + " (" + sha256[:12] + "), nothing to do")
        return dest

    #dest is replaced whole, so it has to be a folder this script filled or an
    #empty one: --dest . from the repo root would take .git with it. asked before
    #the 1.25gb download it would waste
    if os.path.isdir(dest) and os.listdir(dest) and not os.path.exists(stamp_path(dest)):
        raise SystemExit(dest + " holds files and no .sha256, so this script did not put "
                         "them there. point --dest at an empty folder or one it filled before")

    #beside dest rather than in /tmp, which on railway's builder is a small tmpfs
    #that 1.25gb does not fit in, and on the same disk so the swap below is a rename
    parent = os.path.dirname(os.path.abspath(dest))
    os.makedirs(parent, exist_ok=True)
    holding = tempfile.mkdtemp(prefix=".fetch-", dir=parent)
    tar_path = os.path.join(holding, "model.tar")
    unpacked = os.path.join(holding, "model")
    try:
        print("downloading " + rel["file"] + " from " + rel["tag"] + "...")
        got = download(rel["url"], tar_path, rel["bytes"])
        if got != sha256:
            raise SystemExit("sha256 mismatch: model_release.json says " + sha256 +
                             ", the download is " + got + ". the right number of bytes and "
                             "the wrong ones, so the release asset was replaced")
        print("  sha256 ok, extracting...")
        with tarfile.open(tar_path, "r:") as tar:
            #filter="data" refuses absolute paths, "..", links out of the tree
            #and device files. the tar is ours, but an extract that trusts its
            #input is a foothold in an image that also holds nothing else
            tar.extractall(unpacked, filter="data")
        #stamped BEFORE the swap and swapped by rename, so dest is only ever a
        #whole model with its stamp: a failed extract leaves the old one in place,
        #and an older release is never mixed into the new folder
        with open(stamp_path(unpacked), "w", encoding="utf-8") as f:
            f.write(sha256 + "\n")
        if os.path.exists(dest):
            os.rename(dest, os.path.join(holding, "old"))
        os.rename(unpacked, dest)
    finally:
        shutil.rmtree(holding, ignore_errors=True)

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
