#web/ ships copies of things that live elsewhere, because railway only deploys
#web/. they MUST stay identical: if clean_line drifts, the line picker silently
#stops matching page lines to their database rows. the check workflow runs this
#on every push. locally, from the repo root:
#    python tools/check_sync.py
#
#functions are compared by AST, so comments and blank lines do not count and
#behaviour does. the generated prefix_words files are compared byte for byte

import ast
import sys
import os

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
problems = []


def read(path):
    with open(os.path.join(ROOT, path), encoding="utf-8") as f:
        return f.read()


def func_dump(path, name):
    for node in ast.walk(ast.parse(read(path))):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return ast.dump(node)
    problems.append(path + " has no function " + name)
    return None


def assign_value(path, name):
    for node in ast.parse(read(path)).body:
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == name for t in node.targets):
            return ast.literal_eval(node.value)
    problems.append(path + " has no assignment " + name)
    return None


def same(what, a, b, where="between web/ and its source of truth"):
    if a is not None and b is not None and a != b:
        problems.append(what + " drifted " + where)


#every copy web/ carries lives in web/mirror.py. if a name moves out of there,
#this path has to move with it
MIRROR = "web/mirror.py"

#the helper and the keyword list are checked too: clean_line's own ast looks
#identical while either of those quietly says something different
same("clean_line", func_dump(MIRROR, "clean_line"), func_dump("common/cards.py", "clean_line"))
same("reminder_is_the_rule", func_dump(MIRROR, "reminder_is_the_rule"),
     func_dump("common/cards.py", "reminder_is_the_rule"))
same("REMINDER_KEYWORDS", assign_value(MIRROR, "REMINDER_KEYWORDS"),
     assign_value("common/cards.py", "REMINDER_KEYWORDS"))

#which column the vectors are read from. it gets interpolated into sql in both
#places, so the allowlist that keeps it safe has to say the same thing in both
same("embed_column", func_dump(MIRROR, "embed_column"),
     func_dump("ingest/attribute.py", "embed_column"),
     "between web/mirror.py and ingest/attribute.py")
same("EMBED_COLUMNS", assign_value(MIRROR, "EMBED_COLUMNS"),
     assign_value("ingest/attribute.py", "EMBED_COLUMNS"))

#the generated scryfall word catalogs the cleaner leans on
if read("web/prefix_words.py") != read("common/prefix_words.py"):
    problems.append("prefix_words.py drifted between web/ and common/")

#the calibration seeds (the database's meta copy wins at runtime, but the
#seeds cover virgin databases and should agree too)
same("CALIBRATION seed", assign_value(MIRROR, "CALIBRATION"), assign_value("common/concept.py", "CALIBRATION"))
same("MECH_CALIBRATION seed", assign_value(MIRROR, "MECH_CALIBRATION"), assign_value("ingest/update.py", "MECH_CALIBRATION"))

#guarded on the file EXISTING, because finetune/ ships its scripts but not its
#data: a checkout without it has nothing to compare, which must not read as a
#failure
if os.path.exists(os.path.join(ROOT, "finetune", "exam_pairs.py")):
    for fn in ("line_weight", "mech_display"):
        same(fn, func_dump("finetune/exam_pairs.py", fn), func_dump(MIRROR, fn),
             "between finetune/exam_pairs.py and web/mirror.py")
else:
    #a missing folder is not a drift, so this passes. it does mean renaming
    #exam_pairs.py DISABLES the guard rather than failing loudly
    print("no finetune/ here, skipping the exam_pairs drift check")

if problems:
    for p in problems:
        print("DRIFT: " + p)
    sys.exit(1)
print("all web copies match their sources of truth")
