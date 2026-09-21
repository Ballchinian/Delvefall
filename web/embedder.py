#the web side of the embedding service in embed/.
#
#web/ holds no torch on purpose: the model is 1.25gb resident and gunicorn would
#bill that once per worker. so typed text goes over the private network to a
#service that holds it once and sleeps when nobody is typing.
#
#the cost of that is a WAKE. railway stops a sleeping service's container and
#starts it on the next request, and the first request in can be refused while it
#comes up, so the calls below retry rather than fail. /custom pings /health on
#the first keystroke, which usually means the model is loaded by the time
#anybody presses the button.
#
#urllib and not requests: web/requirements.txt is what railway installs on every
#deploy and this needs nothing added to it.

import os
import json
import time
import threading
import urllib.error
import urllib.request

import numpy as np

#unset means no service, which is how this behaves in tests and on a laptop
#that never started one. it is NOT a reason to fall back to something else:
#there is no second way to embed text here
EMBED_URL = os.environ.get("EMBED_URL", "").strip().rstrip("/")

#how long to keep retrying a wake before giving up on it. 90s is the plan's
#figure and M5 measures railway's own request ceiling, which this has to sit
#under: a budget above it means the proxy hangs up first and the visitor gets
#railway's error page instead of the form back with their text still in it
BUDGET = float(os.environ.get("EMBED_BUDGET", "90"))
RETRY_EVERY = 2.0

#gunicorn runs 2 workers of 4 threads, so 8 request threads serve the whole
#site. five people hitting a cold /custom would park five of them for the whole
#budget and /search would queue behind them. past this many waiting, the rest
#are told to come back rather than joining the queue
MAX_WAITING = 3
_waiting = 0
_waiting_lock = threading.Lock()

#the sha256 of the weights that last answered, so /admin can say which model is
#on the other end. it rides on every response rather than needing a call of its
#own, and an empty string means nothing has answered yet this process
_last_sha256 = ""


class EmbedderDown(Exception):
    #the service is asleep, starting, or not there. the page says so and keeps
    #the visitor's text
    pass


class EmbedderRefused(Exception):
    #the service rejected the request itself. read_custom applies the same two
    #limits before calling, so this means the two have drifted apart, which is a
    #bug and should be loud rather than worded as a wake that timed out
    pass


def _post(path, body, timeout):
    req = urllib.request.Request(EMBED_URL + path, data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


#what a waking service answers with while it is still coming up, or what
#railway's proxy answers on its behalf. anything else is a real failure and
#retrying it just spends the budget
WAKING = (502, 503, 504)


def embed(texts):
    #one list of cleaned lines in, one numpy float32 vector per line out, ready
    #to hand straight to pgvector: its adapter sends an ndarray as a vector, and
    #postgres casts vector to halfvec implicitly, so the same code serves the
    #column either side of the rebuild
    if not EMBED_URL:
        raise EmbedderDown("EMBED_URL is not set")

    global _waiting
    with _waiting_lock:
        if _waiting >= MAX_WAITING:
            raise EmbedderDown("too many requests already waiting on the model")
        _waiting += 1
    try:
        deadline = time.monotonic() + BUDGET
        last = None
        while True:
            try:
                body = _post("/embed", {"texts": list(texts)}, timeout=30)
                break
            except urllib.error.HTTPError as e:
                if e.code not in WAKING:
                    detail = ""
                    try:
                        detail = json.loads(e.read()).get("error", "")
                    except Exception:
                        pass
                    raise EmbedderRefused("the model service said %d: %s" % (e.code, detail))
                last = e
            except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
                last = e
            #the sleep happens only when there is budget left to sleep into, so
            #a caller with none waits nothing and is told at once
            if time.monotonic() + RETRY_EVERY >= deadline:
                raise EmbedderDown("the model service did not answer inside %.0fs (%s)" % (BUDGET, last))
            time.sleep(RETRY_EVERY)
    finally:
        with _waiting_lock:
            _waiting -= 1

    global _last_sha256
    _last_sha256 = body.get("sha256", "") or _last_sha256
    vectors = body.get("vectors")
    if not isinstance(vectors, list) or len(vectors) != len(texts):
        raise EmbedderRefused("asked for %d vectors, got %s" % (len(texts), type(vectors).__name__))
    return [np.asarray(v, dtype=np.float32) for v in vectors]


def wake(timeout=1.0):
    #fired at the first keystroke on /custom and never waited on. the point is
    #the packet, not the answer: it is what starts a sleeping container, so the
    #model is loading while somebody is still typing
    if not EMBED_URL:
        return False
    try:
        with urllib.request.urlopen(EMBED_URL + "/health", timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False


def parity(conn, how_many=20):
    #the standing guard against the ingest and the service drifting apart. the
    #service embeds text the ingest already embedded, and the two have to agree:
    #a card's percent is a comparison against the stored vectors, so a service
    #on other weights makes every number on /custom quietly wrong.
    #
    #the bar is the one tools/check_embed_parity.py uses, UNIQUE_NOISE, because
    #an error under it cannot lift a card off the tie at zero. read only, and it
    #WAKES THE SERVICE, so /admin is the only thing that calls it
    if not EMBED_URL:
        return {"ok": False, "why": "EMBED_URL is not set"}
    rows = conn.execute("SELECT line_text, embedding FROM lines WHERE NOT whole "
                        "ORDER BY random() LIMIT %s", (how_many,)).fetchall()
    if not rows:
        return {"ok": False, "why": "no lines to compare against"}
    try:
        fresh = embed([r["line_text"] for r in rows])
    except (EmbedderDown, EmbedderRefused) as e:
        return {"ok": False, "why": str(e)}
    #a halfvec comes back up to 1.2e-4 off length 1, so both sides are
    #renormalised rather than dotted as they are. common/vectors.py does the
    #same for the ingest, and web/ cannot import it
    worst = 1.0
    for row, got in zip(rows, fresh):
        #pgvector hands back its own Vector, not a numpy array, and HalfVector
        #after the rebuild. both answer to_numpy(), and np.asarray of either
        #raises rather than converting
        stored = row["embedding"].to_numpy().astype(np.float32)
        cos = float(np.dot(stored / np.linalg.norm(stored), got / np.linalg.norm(got)))
        worst = min(worst, cos)
    return {"ok": True, "lines": len(rows), "worst": worst, "sha256": _last_sha256}
