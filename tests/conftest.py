#what makes the rest of this folder possible: web/app.py opens a connection at
#import time (the CREATE TABLE block that keeps a railway-only deploy in step
#with common/schema.sql), and web/db.py reads DATABASE_URL out of the
#environment the moment it is imported. neither is wrong, but between them they
#mean "import app" is a database call, and a test suite that needs postgres is a
#test suite the check workflow cannot run.
#
#so a stub module called db goes into sys.modules BEFORE anything imports the
#real one. it answers every query with nothing, which is exactly what the two
#import-time callers can cope with: the DDL block does not read anything back,
#and load_calibration in mirror.py already falls back to its seed maps when the
#lookup comes up empty. that fallback is a bonus rather than a workaround, since
#it means the calibration under test is the documented seed rather than whatever
#the live database happens to hold today.
#
#the stub is also the guard rail. anything that genuinely needs a database gets
#empty rows rather than a connection, so a test that quietly starts depending on
#real data fails here instead of passing on one machine and failing in ci

import os
import sys
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#web/ has to come first: its modules import each other by bare name (db,
#mirror, prefix_words) because railway deploys that folder on its own
sys.path.insert(0, os.path.join(ROOT, "web"))
sys.path.insert(0, ROOT)


class _Result:
    #enough of a cursor for the import-time callers and no more
    def fetchone(self):
        return None

    def fetchall(self):
        return []

    def __iter__(self):
        return iter(())


class _Connection:
    def execute(self, *args, **kwargs):
        return _Result()

    def commit(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _Pool:
    def connection(self):
        return _Connection()


if "db" not in sys.modules:
    stub = types.ModuleType("db")
    stub.pool = _Pool()
    sys.modules["db"] = stub
