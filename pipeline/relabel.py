#!/usr/bin/env python3
"""Safe edits to labels.json / taxonomy.json for audit agents.

Relabel a question (topics are derived from the subtopics, primary first; other label fields kept):
    python3 pipeline/relabel.py set <question_id> <subtopic> [<subtopic> ...] [--note "why"] [--flag topic-uncertain] [--unflag topic-uncertain]

Add a subtopic to the taxonomy (file-locked, safe to run concurrently; prints the new code):
    python3 pipeline/relabel.py add-subtopic <subject> <topic_code> <new_code> "<name>"

Set answer status (and optionally clear/add flags) — locked, safe with concurrent `set`:
    python3 pipeline/relabel.py status <question_id> ok|suspect|missing [--unflag crop-bad] [--flag x] [--note "why"]

Show a question's current labels:
    python3 pipeline/relabel.py get <question_id>

question_id = <exam_id>-q<num>, e.g. physics-2018-M-P2-TZ1-q3 or physics-2011-M-P3-TZ1-qG2.
Every `set` validates and immediately re-merges into exam.json (pipeline/labels.py).
"""

import fcntl
import json
import sys
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import labels as L  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
TAX = ROOT / "db" / "taxonomy.json"


@contextmanager
def locked(path: Path):
    lock = open(str(path) + ".lock", "w")
    fcntl.flock(lock, fcntl.LOCK_EX)
    try:
        yield
    finally:
        fcntl.flock(lock, fcntl.LOCK_UN)
        lock.close()


def split_id(qid):
    i = qid.rfind("-q")
    if i < 0:
        sys.exit(f"bad question id {qid!r}")
    return qid[:i], qid[i + 2:]


def cmd_get(qid):
    eid, num = split_id(qid)
    d = ROOT / "db" / "exams" / eid
    e = json.loads((d / "exam.json").read_text())
    q = next((q for q in e["questions"] if q["num"] == num), None)
    if not q:
        sys.exit(f"{qid}: no such question")
    print(json.dumps({k: q.get(k) for k in ("id", "marks", "qtype", "topics", "subtopics", "flags", "review_note")}, ensure_ascii=False))
    print(f"image: {d / q['image']}")


def cmd_set(qid, args):
    eid, num = split_id(qid)
    d = ROOT / "db" / "exams" / eid
    subs, note, add, rem = [], None, [], []
    it = iter(args)
    for a in it:
        if a == "--note":
            note = next(it)
        elif a == "--flag":
            add.append(next(it))
        elif a == "--unflag":
            rem.append(next(it))
        else:
            subs.append(a)
    if not subs:
        sys.exit("need at least one subtopic")
    exam = json.loads((d / "exam.json").read_text())
    _, sub_parent = L.taxonomy(exam["subject"])
    bad = [s for s in subs if s not in sub_parent]
    if bad:
        sys.exit(f"unknown subtopic(s) {bad} for {exam['subject']}")
    topics = list(dict.fromkeys(sub_parent[s] for s in subs))
    with locked(d / "labels.json"):
        lp = d / "labels.json"
        labels = json.loads(lp.read_text()) if lp.exists() else {"exam_id": eid, "questions": {}}
        lab = labels["questions"].setdefault(num, {})
        lab["subtopics"], lab["topics"] = list(dict.fromkeys(subs)), topics
        if add or rem:
            flags = [f for f in lab.get("add_flags", []) if f not in rem] + [f for f in add if f not in lab.get("add_flags", [])]
            lab["add_flags"] = flags
        if note:
            lab["note"] = (lab.get("note", "") + " | audit: " + note).strip(" |")
        errs = L.validate(exam, labels)
        if errs:
            sys.exit("not saved:\n  " + "\n  ".join(errs))
        L.write_json_atomic(lp, labels)
        merged = L.merge_labels(exam, d)
        if rem:  # flags removed from labels must also leave exam.json
            for q in merged["questions"]:
                if q["num"] == num:
                    q["flags"] = [f for f in q.get("flags", []) if f not in rem]
        L.write_json_atomic(d / "exam.json", merged)
    print(f"{qid}: topics={topics} subtopics={subs}")


def cmd_status(qid, args):
    """status <qid> <ok|suspect|missing> [--unflag crop-bad] [--flag x] [--note "..."] — answer status only."""
    eid, num = split_id(qid)
    d = ROOT / "db" / "exams" / eid
    status, rest = args[0], args[1:]
    if status not in L.ANSWER:
        sys.exit(f"status must be one of {sorted(L.ANSWER)}")
    note, add, rem = None, [], []
    it = iter(rest)
    for a in it:
        if a == "--note":
            note = next(it)
        elif a == "--flag":
            add.append(next(it))
        elif a == "--unflag":
            rem.append(next(it))
    exam = json.loads((d / "exam.json").read_text())
    with locked(d / "labels.json"):
        lp = d / "labels.json"
        labels = json.loads(lp.read_text()) if lp.exists() else {"exam_id": eid, "questions": {}}
        lab = labels["questions"].setdefault(num, {})
        lab["answer_status"] = status
        if add or rem:
            lab["add_flags"] = [f for f in lab.get("add_flags", []) if f not in rem] + [f for f in add if f not in lab.get("add_flags", [])]
        if note:
            lab["note"] = (lab.get("note", "") + " | " + note).strip(" |")
        errs = L.validate(exam, labels)
        if errs:
            sys.exit("not saved:\n  " + "\n  ".join(errs))
        L.write_json_atomic(lp, labels)
        merged = L.merge_labels(exam, d)
        for q in merged["questions"]:
            if q["num"] == num and rem:
                q["flags"] = [f for f in q.get("flags", []) if f not in rem]
        L.write_json_atomic(d / "exam.json", merged)
    print(f"{qid}: answer_status={status}")


def cmd_add_subtopic(subject, topic, code, name):
    with locked(TAX):
        tax = json.loads(TAX.read_text())
        tp = next((t for t in tax[subject]["topics"] if t["code"] == topic), None)
        if not tp:
            sys.exit(f"no topic {topic} in {subject}")
        all_codes = {s["code"] for t in tax[subject]["topics"] for s in t["subtopics"]}
        if code in all_codes:
            sys.exit(f"{code} already exists")
        tp["subtopics"].append({"code": code, "name": name})
        L.write_json_atomic(TAX, tax)
    L._tax_cache.clear()
    print(f"added {subject} {code} {name!r} under {topic}")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    c = sys.argv[1]
    if c == "get":
        cmd_get(sys.argv[2])
    elif c == "set":
        cmd_set(sys.argv[2], sys.argv[3:])
    elif c == "status":
        cmd_status(sys.argv[2], sys.argv[3:])
    elif c == "add-subtopic":
        cmd_add_subtopic(*sys.argv[2:6])
    else:
        sys.exit(__doc__)
