#one shared connection pool for the whole app. register_vector teaches each
#connection the pgvector column type, so embeddings come back as arrays that can
#go straight into the next query

import os

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
from pgvector.psycopg import register_vector

def setup(conn):
    register_vector(conn)
    #ef_search doubles as the scan's result CAP, so it has to cover the LIMIT
    #400. the iterative scan keeps walking the graph in order when filters
    #discard candidates
    conn.execute("SET hnsw.ef_search = 400")
    conn.execute("SET hnsw.iterative_scan = 'strict_order'")
    conn.commit()  #the type lookup opens a transaction, close it or the pool complains


#min_size keeps four open and WARM: opening one mid request costs a tls
#handshake the visitor waits on, and a multi-line search borrows up to three at
#once for its side-by-side scans.
#
#max is sized off the arithmetic: gunicorn runs 4 threads per worker and a search
#takes up to 3 connections, so one worker can want 12. a pool holding fewer
#queues against `timeout` (30s) and then raises PoolTimeout, which reaches the
#visitor as a 500 on a page that was only busy.
#
#TEN and not twelve, four threads each running a three-line search in the same
#instant being the worst case rather than the common one. the pool only opens
#past min_size when asked, so this costs nothing at rest. at 2 workers it is 20
#against the 97 connections this server leaves usable
pool = ConnectionPool(
    os.environ["DATABASE_URL"],
    min_size=4,
    max_size=10,
    kwargs={"row_factory": dict_row},
    configure=setup,
    open=True,
)
