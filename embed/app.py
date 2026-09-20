#the embedding model behind /custom, in a service of its own.
#
#it exists because web/ must not hold torch: the model is 1.25gb resident and
#gunicorn would bill that once per worker. here it is billed once, and railway's
#serverless setting stops billing it at all a few minutes after the last
#request. the first request after that pays the wake.
#
#IT TALKS TO NOTHING. no database, no hugging face, no outbound anything: a
#service that opens a connection never goes idle and never sleeps, so the two
#offline flags below are a cost control as much as a privacy one.
#
#nothing typed here is stored or logged. the text arrives cleaned, turns into
#768 numbers, and goes back in the response.

import os

#before sentence_transformers is imported, or it phones home to check for a
#newer snapshot of a model that is already on disk
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

from flask import Flask, jsonify, request
from sentence_transformers import SentenceTransformer

#the prefix was glued to the front of every line during training, and encoding
#without it gives useless vectors. IDENTICAL to ingest/update.py's, which
#tools/check_sync.py enforces: the table was embedded with one of these and a
#visitor's text with the other, and they have to be the same string
EMBED_PROMPT = "task: sentence similarity | query: "

#what web/ sends in one request. the most lines on a stored card is 19 and the
#longest stored line is 510 characters, so anything past these is not a card
MAX_TEXTS = 20
MAX_CHARS = 600

MODEL_DIR = os.environ.get("EMBED_MODEL_DIR", "/model")


def model_sha256():
    #written by fetch_model.py after the extract finished. it rides on every
    #answer so /admin can compare what answered against what the ingest used
    try:
        with open(os.path.join(MODEL_DIR, ".sha256"), encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


SHA256 = model_sha256()

#at import, not on first request: gunicorn's worker boots, loads 1.25gb over
#about three seconds, and only then takes traffic. loading lazily would put
#those seconds inside somebody's page load instead
model = SentenceTransformer(MODEL_DIR, device="cpu")

app = Flask(__name__)


@app.get("/health")
def health():
    #what railway wakes the service with, and what /custom's wake ping hits on
    #the first keystroke. it touches the model not at all: the answer is that
    #the worker is up, which is the slow part
    return jsonify({"ok": True, "sha256": SHA256})


@app.post("/embed")
def embed():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify({"error": "send a json object"}), 400
    texts = body.get("texts")
    if not isinstance(texts, list) or not texts:
        return jsonify({"error": "texts must be a non-empty list"}), 400
    if len(texts) > MAX_TEXTS:
        return jsonify({"error": "at most %d texts, got %d" % (MAX_TEXTS, len(texts))}), 400
    for t in texts:
        if not isinstance(t, str):
            return jsonify({"error": "every text must be a string"}), 400
        if len(t) > MAX_CHARS:
            return jsonify({"error": "at most %d characters a text" % MAX_CHARS}), 400

    #the call ingest/update.py makes, argument for argument. batch_size is 64
    #there and stays 64 here even though nothing sends 64: sentence-transformers
    #sorts by length inside a batch, so the number is part of the answer
    vectors = model.encode(texts, batch_size=64, show_progress_bar=False,
                           normalize_embeddings=True, prompt=EMBED_PROMPT)
    #float32 widened to double and written by repr() comes back the same
    #float32, so the json round trip costs no precision. the accuracy bar this
    #whole service was chosen for is 1.8e-7, well inside what a lossy one
    #would spend
    return jsonify({"vectors": [[float(x) for x in row] for row in vectors],
                    "sha256": SHA256})
