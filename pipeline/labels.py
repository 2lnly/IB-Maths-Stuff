#!/usr/bin/env python3
"""Merge hand/agent-made labels into segmented exams, with validation.

Each exam dir may contain `labels.json` (written by classifier agents, never by the segmenter):

{
  "exam_id": "physics-2018-M-P2-TZ1",
  "questions": {
    "3": {
      "topics": ["A", "D"],             # taxonomy topic codes, primary first (must equal parents of subtopics)
      "subtopics": ["A.2", "D.1"],      # taxonomy subtopic codes, most marks first
      "text_clean": "...",              # optional faithful transcription of the question (LaTeX $...$ for maths)
      "qtype": "long",                  # optional override
      "marks": 9,                       # optional override
      "answer_status": "suspect",       # optional override: ok | missing | suspect
      "add_flags": ["topic-uncertain"], # optional flags to add
      "note": "free text"               # optional reviewer note (kept in exam.json as review_note)
    }
  },
  "exam_note": "optional"
}

Usage:
    python3 pipeline/labels.py --check <exam_id> [...]     # validate labels.json only (non-zero exit on error)
    python3 pipeline/labels.py --apply <exam_id> [...]     # validate + merge into exam.json
    python3 pipeline/labels.py --apply-all                 # every exam dir with a labels.json
    python3 pipeline/labels.py --stats                     # coverage summary

segment.py calls merge_labels() automatically, so re-segmenting an exam keeps its labels.
"""

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXAMS = ROOT / "db" / "exams"
QTYPES = {"mcq", "short", "long", "essay", "data"}
ANSWER = {"ok", "missing", "suspect"}

_tax_cache = {}


def taxonomy(subject):
    if not _tax_cache:
        tax = json.loads((ROOT / "db" / "taxonomy.json").read_text())
        for subj, t in tax.items():
            topics, subs = set(), {}
            for tp in t["topics"]:
                topics.add(tp["code"])
                for st in tp.get("subtopics", []):
                    subs[st["code"]] = tp["code"]
            _tax_cache[subj] = (topics, subs)
    return _tax_cache[subject]


def validate(exam: dict, labels: dict) -> list[str]:
    errs = []
    topics_ok, subs_ok = taxonomy(exam["subject"])
    nums = {q["num"] for q in exam.get("questions", [])}
    lq = labels.get("questions", {})
    if not isinstance(lq, dict):
        return ["labels.questions must be an object keyed by question num"]
    for num, lab in lq.items():
        where = f"q{num}"
        if num not in nums:
            errs.append(f"{where}: no such question in exam.json (nums: {sorted(nums)})")
            continue
        tps, sts = lab.get("topics"), lab.get("subtopics")
        if tps is not None or sts is not None:
            tps, sts = tps or [], sts or []
            for t in tps:
                if t not in topics_ok:
                    errs.append(f"{where}: unknown topic {t!r}")
            for s in sts:
                if s not in subs_ok:
                    errs.append(f"{where}: unknown subtopic {s!r}")
            parents = []
            for s in sts:
                p = subs_ok.get(s)
                if p and p not in parents:
                    parents.append(p)
            if sts and set(parents) != set(tps):
                errs.append(f"{where}: topics {tps} must equal the parents of subtopics {parents}")
            if not tps:
                errs.append(f"{where}: empty topics")
            if len(set(tps)) != len(tps) or len(set(sts)) != len(sts):
                errs.append(f"{where}: duplicate codes")
        if "qtype" in lab and lab["qtype"] not in QTYPES:
            errs.append(f"{where}: bad qtype {lab['qtype']!r}")
        if "answer_status" in lab and lab["answer_status"] not in ANSWER:
            errs.append(f"{where}: bad answer_status {lab['answer_status']!r}")
        if "marks" in lab and not (lab["marks"] is None or isinstance(lab["marks"], int)):
            errs.append(f"{where}: marks must be int or null")
        if "text_clean" in lab and not isinstance(lab["text_clean"], str):
            errs.append(f"{where}: text_clean must be a string")
    return errs


def merge_labels(exam: dict, out_dir: Path) -> dict:
    """Apply out_dir/labels.json onto an exam dict (in memory). Raises ValueError on invalid labels."""
    lp = out_dir / "labels.json"
    if not lp.exists():
        return exam
    labels = json.loads(lp.read_text())
    errs = validate(exam, labels)
    if errs:
        raise ValueError(f"{exam['exam_id']} labels.json invalid:\n  " + "\n  ".join(errs))
    lq = labels.get("questions", {})
    for q in exam.get("questions", []):
        lab = lq.get(q["num"])
        if not lab:
            continue
        for k in ("topics", "subtopics", "text_clean", "qtype", "marks", "answer_status"):
            if k in lab:
                q[k] = lab[k]
        if lab.get("add_flags"):
            q["flags"] = list(dict.fromkeys((q.get("flags") or []) + lab["add_flags"]))
        if lab.get("note"):
            q["review_note"] = lab["note"]
    if labels.get("exam_note"):
        exam["review_note"] = labels["exam_note"]
    return exam


def write_json_atomic(path: Path, data):
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=".json")
    with os.fdopen(fd, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", nargs="*")
    ap.add_argument("--apply", nargs="*")
    ap.add_argument("--apply-all", action="store_true")
    ap.add_argument("--stats", action="store_true")
    a = ap.parse_args()

    if a.stats:
        from collections import Counter
        c = Counter()
        for d in sorted(EXAMS.iterdir()):
            if not (d / "exam.json").exists():
                continue
            e = json.loads((d / "exam.json").read_text())
            s = e["subject"]
            c[(s, "exams")] += 1
            c[(s, "labelled_exams")] += (d / "labels.json").exists()
            for q in e["questions"]:
                c[(s, "questions")] += 1
                c[(s, "classified")] += bool(q.get("topics"))
                c[(s, "multi_topic")] += len(q.get("topics") or []) > 1
                c[(s, "text_clean")] += bool(q.get("text_clean"))
                c[(s, "ans_" + q.get("answer_status", "?"))] += 1
        for s in ("math", "physics", "economics"):
            print(s, {k[1]: v for k, v in c.items() if k[0] == s})
        return

    ids = a.check if a.check is not None else a.apply
    if a.apply_all:
        ids = [d.name for d in sorted(EXAMS.iterdir()) if (d / "labels.json").exists()]
    if not ids:
        ap.print_help()
        return
    bad = 0
    for eid in ids:
        d = EXAMS / eid
        try:
            exam = json.loads((d / "exam.json").read_text())
            if a.check is not None:
                errs = validate(exam, json.loads((d / "labels.json").read_text()))
                if errs:
                    raise ValueError("\n  ".join(errs))
                print(f"ok      {eid}")
            else:
                write_json_atomic(d / "exam.json", merge_labels(exam, d))
                print(f"applied {eid}")
        except Exception as ex:
            bad += 1
            print(f"ERROR   {eid}: {ex}")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
