#every ingest step writes to tables the site reads, so each one takes the same
#advisory lock before its first write. a step that forgets it can interleave with
#a rebuild, which is what the lock is there to stop

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


class TestEveryIngestStepTakesTheLock:

    def test_nothing_opens_a_connection_without_it(self):
        #where each one takes it is its own business: the steps take it in main
        #before schema.sql, rebuild_lines.py inside the calls that write
        for name, tree in modules():
            made = calls(tree)
            if "psycopg.connect" not in made:
                continue
            assert [c for c in made if c.startswith("locks.")], name + " connects without taking the lock"
