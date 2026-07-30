#edhrec's annual salt survey into cards.salt, by way of mtgjson's AtomicCards
#(edhrecSaltiness). scryfall does not carry this number at all, hence a second
#source.
#    python -m ingest.salt
#with DATABASE_URL set. reruns are free, the meta gate skipping the work unless
#mtgjson published a newer version.
#
#the votes are stored AS CAST, protest votes included: dropping the ones that
#look wrong would mean the column stops measuring what it claims to.
#
#158mb of json for one float per card, so this takes the .xz (25mb) and streams
#it through ijson. joined on oracle id with no name matching, like decks.py

import os
import sys
import lzma

import ijson
import psycopg
import requests

from common.cards import HEADERS
from ingest.update import get_with_retries

META_URL = "https://mtgjson.com/api/v5/Meta.json"
ATOMIC_URL = "https://mtgjson.com/api/v5/AtomicCards.json.xz"
ATOMIC_FILE = "AtomicCards.json.xz"

#its own key, separate from decks.py's. sharing 'mtgjson_version' would mean
#whichever ran second saw it already recorded and skipped itself forever
META_KEY = "mtgjson_salt_version"


def download(url, path):
    print("downloading " + url + " (~25mb compressed, 158mb of json inside)")
    for attempt in range(3):
        try:
            with requests.get(url, headers=HEADERS, timeout=300, stream=True) as r:
                r.raise_for_status()
                with open(path, "wb") as f:
                    for chunk in r.iter_content(chunk_size=1024 * 1024):
                        f.write(chunk)
            return
        except Exception as e:
            if attempt == 2:
                raise
            print("download failed (" + str(e) + "), retrying...")


def read_salt(path):
    #AtomicCards is keyed by card NAME with a list of faces under each, so
    #kvitems walks the names and the faces carry the oracle id to join on. both
    #faces share a score (edhrec rates whole cards), so the first one wins
    out = {}
    with lzma.open(path, "rb") as f:
        for name, faces in ijson.kvitems(f, "data"):
            for face in faces:
                salt = face.get("edhrecSaltiness")
                oid = (face.get("identifiers") or {}).get("scryfallOracleId")
                if salt is None or not oid:
                    continue
                out[oid] = float(salt)
                break
    return out


def main():
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("set DATABASE_URL first (the postgres connection string)")
        sys.exit(1)

    conn = psycopg.connect(db_url)
    schema_path = os.path.join(os.path.dirname(__file__), "..", "common", "schema.sql")
    with open(schema_path, encoding="utf-8") as f:
        conn.execute(f.read())
    conn.commit()

    #through the retrier: a single 502 would otherwise fail the step that decides
    #whether there is any work to do at all
    print("asking mtgjson for its version...")
    version = get_with_retries(META_URL).json()["data"]["version"]

    #an empty salt column means a first run, or one that died halfway
    row = conn.execute("SELECT value FROM meta WHERE key = %s", (META_KEY,)).fetchone()
    if (row and row[0] == version
            and conn.execute("SELECT 1 FROM cards WHERE salt IS NOT NULL LIMIT 1").fetchone()):
        print("already processed mtgjson " + version + ", nothing to do")
        conn.close()
        return

    download(ATOMIC_URL, ATOMIC_FILE)
    print("streaming the salt scores out of it...")
    salt = read_salt(ATOMIC_FILE)
    print("mtgjson has salt for " + str(len(salt)) + " cards")

    #a temp table and one update, rather than 31k round trips. IS DISTINCT FROM
    #keeps unchanged rows from being rewritten, which with a yearly survey is
    #every one of them
    with conn.cursor() as cur:
        cur.execute("CREATE TEMP TABLE salt_tmp (oracle_id uuid PRIMARY KEY, salt real) ON COMMIT DROP")
        with cur.copy("COPY salt_tmp (oracle_id, salt) FROM STDIN") as copy:
            for oid, value in salt.items():
                copy.write_row((oid, value))
        cur.execute("""
            UPDATE cards c SET salt = t.salt
            FROM salt_tmp t
            WHERE c.oracle_id = t.oracle_id AND c.salt IS DISTINCT FROM t.salt
        """)
        touched = cur.rowcount
        cur.execute("INSERT INTO meta (key, value) VALUES (%s, %s) "
                    "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value", (META_KEY, version))
    conn.commit()

    have = conn.execute("SELECT count(*) FROM cards WHERE salt IS NOT NULL").fetchone()[0]
    total = conn.execute("SELECT count(*) FROM cards").fetchone()[0]
    print("updated " + str(touched) + " cards, " + str(have) + "/" + str(total) + " now carry a salt score")
    conn.close()

    #a quarter of a gigabyte uncompressed, not left behind on the runner
    try:
        os.remove(ATOMIC_FILE)
    except OSError:
        pass


if __name__ == "__main__":
    main()
