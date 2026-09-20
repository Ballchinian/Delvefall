#packs the embedding weights into the tar that becomes a github release asset,
#and writes embed/model_release.json so embed/fetch_model.py can find it.
#
#    python tools/build_model_release.py --source <a snapshot folder> [--out <dir>]
#
#source is a sentence-transformers folder, normally the hugging face cache
#snapshot: ~/.cache/huggingface/hub/models--BallchinianMan--mtg-tagtuned-embeddinggemma-300m/snapshots/<revision>
#NOT finetune/models/, which holds v1, the wrong model.
#
#run tools/check_embed_parity.py against the same folder FIRST. this script
#checks that the files are there and the tar unpacks; it cannot tell one set of
#weights from another, and the whole point of the release is that both runners
#get the ones the table was embedded with.
#
#the tar is UNCOMPRESSED: safetensors is already dense float data and gzip
#spends minutes to save about a percent, on every docker build.
#
#it is also REPRODUCIBLE. names sorted, timestamps and ownership flattened, so
#building it twice from the same folder gives the same sha256 and the hash in
#model_release.json is something anyone can check rather than something only
#this machine ever saw.

import os
import sys
import json
import time
import hashlib
import tarfile
import argparse

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
NOTICE = os.path.join(ROOT, "embed", "NOTICE")
RELEASE = os.path.join(ROOT, "embed", "model_release.json")

REPO = "Ballchinian/Delvefall"
NAME = "mtg-tagtuned-embeddinggemma-300m"

#a sentence-transformers folder that is missing any of these loads as something
#else, quietly: no modules.json and it falls back to mean pooling over raw
#hidden states, which is not what embedded the table
REQUIRED = ("config.json", "config_sentence_transformers.json", "modules.json",
            "model.safetensors", "tokenizer.json", "tokenizer_config.json")

CHUNK = 1 << 20


def files_in(source):
    out = []
    for dirpath, dirnames, filenames in os.walk(source):
        dirnames.sort()
        for name in sorted(filenames):
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, source).replace(os.sep, "/")
            #the cache keeps its bookkeeping beside the weights on some
            #platforms, and a lock file in the image is just confusing
            if rel.startswith(".") or rel.endswith(".lock"):
                continue
            out.append((rel, full))
    return sorted(out)


def build(source, out_dir, revision):
    missing = [f for f in REQUIRED if not os.path.exists(os.path.join(source, f))]
    if missing:
        raise SystemExit(source + " is missing " + ", ".join(missing) +
                         ". is this a sentence-transformers folder?")

    members = files_in(source)
    tar_name = NAME + "-" + revision[:7] + ".tar"
    tar_path = os.path.join(out_dir, tar_name)
    os.makedirs(out_dir, exist_ok=True)

    print("packing " + str(len(members) + 1) + " files into " + tar_path)
    with tarfile.open(tar_path, "w", format=tarfile.PAX_FORMAT) as tar:
        for rel, full in members + [("NOTICE", NOTICE)]:
            info = tarfile.TarInfo(rel)
            info.size = os.path.getsize(full)
            #flattened, so the hash depends on the bytes and not on when this
            #ran or who ran it
            info.mtime = 0
            info.mode = 0o644
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            with open(full, "rb") as f:
                tar.addfile(info, f)
            print("  %-42s %9.1f mb" % (rel, info.size / 1e6))

    digest = hashlib.sha256()
    with open(tar_path, "rb") as f:
        while True:
            chunk = f.read(CHUNK)
            if not chunk:
                break
            digest.update(chunk)
    sha256 = digest.hexdigest()

    tag = "model-" + revision[:7]
    record = {
        "tag": tag,
        "file": tar_name,
        "url": "https://github.com/" + REPO + "/releases/download/" + tag + "/" + tar_name,
        "sha256": sha256,
        "hf_revision": revision,
        "hf_repo": "BallchinianMan/" + NAME,
        "bytes": os.path.getsize(tar_path),
        "built": time.strftime("%Y-%m-%d"),
    }
    with open(RELEASE, "w", encoding="utf-8", newline="\n") as f:
        json.dump(record, f, indent=2)
        f.write("\n")

    print("\n%.2f gb, sha256 %s" % (record["bytes"] / 1e9, sha256))
    print("wrote embed/model_release.json")
    print("\nnext, by hand:")
    print("  1. gh release create " + tag + " " + tar_path + " --repo " + REPO)
    print("     (or the releases page: new release, tag " + tag + ", attach the tar)")
    print("  2. python embed/fetch_model.py --dest <a scratch folder>   to prove the url and hash")
    print("  3. commit embed/model_release.json")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True, help="the sentence-transformers folder to pack")
    #no default, and outside the repo: 1.25gb sitting in the working tree is one
    #stray `git add .` away from a push that github refuses halfway through
    ap.add_argument("--out", required=True, help="a folder OUTSIDE the repo to write the tar into")
    ap.add_argument("--revision", help="the hugging face revision. default: the source folder's name")
    args = ap.parse_args()
    revision = args.revision or os.path.basename(os.path.normpath(args.source))
    if len(revision) < 7:
        raise SystemExit("--revision looks wrong (" + revision + "): it names the tag and the file")
    build(args.source, args.out, revision)


if __name__ == "__main__":
    sys.exit(main())
