#every ingest step writes to tables the site reads, so each one takes the same
#advisory lock before its first write. a step that forgets it can interleave with
#a rebuild, which is what the lock is there to stop.
#
#and each one opens its connection the same way, for the same reason: the lock a
#step holds is only ever let go by the step ending

import ast
import os

from conftest import ROOT


def modules():
    for name in sorted(os.listdir(os.path.join(ROOT, "ingest"))):
        if name.endswith(".py") and name != "__init__.py":
            with open(os.path.join(ROOT, "ingest", name), encoding="utf-8") as f:
                yield name, ast.parse(f.read())


def calls(tree):
    return [ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)]


def connects(tree):
    return [n for n in ast.walk(tree) if isinstance(n, ast.Call)
            and ast.unparse(n.func) == "psycopg.connect"]


class TestEveryIngestStepTakesTheLock:

    def test_nothing_opens_a_connection_without_it(self):
        #where each one takes it is its own business: the steps take it in main
        #before schema.sql, rebuild_lines.py inside the calls that write. one call
        #anywhere passes this, so a branch of rebuild_lines' main that skips it
        #does too: test_rebuild_lines runs each of its actions against a held lock
        for name, tree in modules():
            made = calls(tree)
            if "psycopg.connect" not in made:
                continue
            assert [c for c in made if c.startswith("locks.")], name + " connects without taking the lock"


class TestEveryIngestConnectionCanDie:

    def test_none_of_them_is_opened_without_the_keepalives(self):
        #a step whose socket is black holed holds its transaction until the job
        #times out hours later, and the site's own boot queues behind it
        for name, tree in modules():
            for call in connects(tree):
                spread = [k.value for k in call.keywords if k.arg is None]
                assert [v for v in spread if ast.unparse(v) == "KEEPALIVE"], (
                    name + " opens a connection that can hang forever")
