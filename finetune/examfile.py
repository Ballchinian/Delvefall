#the one reader for every hand-marked exam file in testing_list/.
#
#they all have the same shape, so they all parse the same way and none of them
#can drift from the code that scores it:
#
#    # Title
#
#    What it scores. Read at runtime by `some_exam.py`.
#
#    ## Section
#
#    What passing means, one line.
#
#    1.
#        **Anchor:** Murder - `Destroy target creature.`
#        **NOT:** Day of Judgment - `Destroy all creatures.`
#        *one short reason*
#
#prose that is not a numbered entry is for people and is skipped, so the files
#stay readable without the parser caring. sections are returned in file order.

import os
import re

TESTING_LIST = os.path.join(os.path.dirname(os.path.abspath(__file__)), "testing_list")

ENTRY = re.compile(r"^\d+\.\s*$")
FIELD = re.compile(r"^\s+\*\*(.+?):\*\*\s*(.*?)\s*$")
NOTE = re.compile(r"^\s+\*(?!\*)(.+?)\*\s*$")
HEAD = re.compile(r"^##\s+(.+?)\s*$")


def path(name):
    #testing_list/<name>.md, the file named for the script that owns it
    return os.path.join(TESTING_LIST, name + ".md")


def read(name):
    #{section title: [{"fields": {label: text}, "note": str}]}
    sections, cur, entry = {}, None, None
    with open(path(name), encoding="utf-8") as f:
        for line in f:
            h = HEAD.match(line)
            if h:
                cur = h.group(1)
                sections.setdefault(cur, [])
                entry = None
                continue
            if ENTRY.match(line):
                entry = {"fields": {}, "note": ""}
                if cur is not None:
                    sections[cur].append(entry)
                continue
            if entry is None:
                continue
            m = FIELD.match(line)
            if m:
                entry["fields"][m.group(1)] = m.group(2)
                continue
            m = NOTE.match(line)
            if m:
                entry["note"] = m.group(1)
    return sections


def card_lines(value):
    #"Merfolk Looter - `{T}: Draw a card.` + `Flying`" -> (name, [line, line]).
    #a candidate card carries every line the engine would see for it, so the
    #backticks are counted rather than assumed to be one
    name, _, rest = value.partition(" - ")
    lines = re.findall(r"`([^`]*)`", rest)
    return name.strip(), lines


def card_only(value):
    #for the exams that name cards and never quote a line
    return value.split(" - ")[0].strip()
