#one advisory lock, so the daily ingest and any maintenance tool never write to
#the tables the site reads at the same time. the clock cannot do this job:
#update.yml asks for 9 utc and github has started it anywhere from 12:43 to 15:46.
#
#postgres ties the lock to the connection, not to a transaction: it survives a
#rollback and goes when the connection closes, a crashed run included. the number
#is arbitrary and only has to match on both sides
INGEST = 5308714


def hold(conn):
    #waits its turn. the ingest is a batch job, so waiting out a rebuild costs it
    #minutes and costs the site nothing
    conn.execute("SELECT pg_advisory_lock(%s)", (INGEST,))


def claim(conn):
    #for the tool that would rather say so than queue behind a 12 minute ingest
    return conn.execute("SELECT pg_try_advisory_lock(%s)", (INGEST,)).fetchone()[0]
