#one shared connection pool for the whole app. every request borrows a
#connection, runs its queries and hands it right back. register_vector
#teaches each connection about the pgvector column type so embeddings come
#back as arrays we can pass straight into the next query

import os

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
from pgvector.psycopg import register_vector

def setup(conn):
    register_vector(conn)
    #hnsw scan settings for the search. ef_search doubles as the scan's
    #result cap so it must cover the LIMIT 400, and the iterative scan
    #keeps walking the graph in order when filters discard candidates
    conn.execute("SET hnsw.ef_search = 400")
    conn.execute("SET hnsw.iterative_scan = 'strict_order'")
    conn.commit()  #the type lookup opens a transaction, close it or the pool complains


#railway hands you this connection string, see the readme for setup.
#
#min_size keeps four open and warm, and that is the latency decision: opening a
#connection mid request costs a tls handshake the visitor waits on, and a
#multi-line search borrows up to three at once for its side-by-side line scans.
#
#max is the larger number, and the sum is why. the Procfile runs gunicorn with
#4 threads per worker and a search takes up to 3 connections, so one worker can
#genuinely want 12. a pool holding fewer does not error, it queues, but it
#queues against `timeout` (30s) and then raises PoolTimeout, which reaches the
#visitor as a 500 on a page that was only busy.
#
#ten rather than twelve, because the ceiling is not the thing to size against.
#four threads each running a three-line search in the same instant is the worst
#case rather than the common one, and the pool only opens past min_size when it
#is actually asked to, so this costs nothing at rest. at 2 workers it is 20
#connections against the 97 this server leaves usable
pool = ConnectionPool(
    os.environ["DATABASE_URL"],
    min_size=4,
    max_size=10,
    kwargs={"row_factory": dict_row},
    configure=setup,
    open=True,
)
