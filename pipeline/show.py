#!/usr/bin/env python3
"""Compact views for classifier/reviewer agents.

    python3 pipeline/show.py exam <exam_id> [--full]   # exam header + every question (text, ms excerpt, files)
    python3 pipeline/show.py taxonomy <subject>        # subject taxonomy as an indented code list
    python3 pipeline/show.py guide <subject>           # CLASSIFY.md rules + this subject's mapping/examples only
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def clip(s, n):
    s = re.sub(r"[ \t]+", " ", (s or "").strip())
    return s if len(s) <= n else s[:n] + f" …[+{len(s) - n} chars]"


def exam(eid, full=False):
    d = ROOT / "db" / "exams" / eid
    e = json.loads((d / "exam.json").read_text())
    keys = ("exam_id", "subject", "syllabus", "year", "session", "tz", "paper", "option", "level", "status", "qp_pages")
    print(" | ".join(f"{k}={e.get(k)}" for k in keys))
    print(f"qp_pdf: {e.get('qp_pdf')}\nms_pdf: {e.get('ms_pdf')}")
    if e.get("notes"):
        print("notes:", clip(e["notes"], 900))
    print(f"dir: {d}")
    lab = d / "labels.json"
    print("labels.json:", "EXISTS" if lab.exists() else "none")
    for q in e["questions"]:
        print("\n" + "=" * 100)
        print(f"Q {q['num']}  section={q.get('section')} option={q.get('option')} marks={q.get('marks')} "
              f"qtype={q.get('qtype')} answer_status={q.get('answer_status')} mcq={q.get('mcq_answer')} "
              f"flags={q.get('flags')}")
        print(f"image: {d / q['image']}" if q.get("image") else "image: NONE")
        print(f"ms_image: {d / q['ms_image']}" if q.get("ms_image") else "ms_image: NONE")
        if q.get("topics"):
            print(f"current topics={q['topics']} subtopics={q.get('subtopics')}")
        print("--- text:\n" + (q.get("text") or "") if full else "--- text: " + clip(q.get("text"), 1500))
        print("--- ms_text:\n" + (q.get("ms_text") or "") if full else "--- ms_text: " + clip(q.get("ms_text"), 1200))


def taxonomy(subject):
    t = json.loads((ROOT / "db" / "taxonomy.json").read_text())[subject]
    for tp in t["topics"]:
        print(f"{tp['code']}  {tp['name']}")
        for st in tp.get("subtopics", []):
            print(f"    {st['code']}  {st['name']}")


def guide(subject):
    text = (ROOT / "db" / "CLASSIFY.md").read_text()
    parts = re.split(r"(?m)^(?=#{2,3} )", text)
    want = {"math": ("Math",), "physics": ("Physics",), "economics": ("Economics",)}[subject]
    out = []
    for p in parts:
        head = p.splitlines()[0] if p.strip() else ""
        if head.startswith("### "):
            if any(w.lower() in head.lower() for w in want):
                out.append(p)
        else:
            out.append(p)
    print("".join(out))


def reports(subject):
    """Stage-2 reviewer reports (problems, crop fixes, non-ok answers) for one subject."""
    res = json.loads((ROOT / ".scratch" / "stage2_results.json").read_text())
    for r in res:
        if not r["exam_ids"][0].startswith(subject + "-"):
            continue
        p = re.sub(r"\s+", " ", r.get("problems", "")).strip()
        if re.match(r"^none\b", p, re.I) and not r["crop_fixes"] and not r["suspect_or_missing"]:
            continue
        print("##", " + ".join(r["exam_ids"]))
        for f in r["crop_fixes"]:
            print("   fixed:", f)
        for s in r["suspect_or_missing"]:
            print("   not-ok:", s)
        if p:
            print("   problems:", p)


def audit_rows(subject, topic):
    rows = []
    for d in sorted((ROOT / "db" / "exams").iterdir()):
        f = d / "exam.json"
        if not d.name.startswith(subject + "-") or not f.exists():
            continue
        e = json.loads(f.read_text())
        for q in e["questions"]:
            if topic in (q.get("topics") or []):
                subs = q.get("subtopics") or []
                own = [s for s in subs if s.split(".")[0] == topic] or ["-"]
                rows.append((own[0], e, q))
    rows.sort(key=lambda r: (r[0], str(r[1]["year"]), r[2]["id"]))
    return rows


def audit(subject, topic, part="1/1"):
    """Every question tagged with `topic`, grouped by its first subtopic in that topic. --part i/n splits it."""
    i, n = map(int, part.split("/"))
    rows = audit_rows(subject, topic)
    size = -(-len(rows) // n)
    chunk = rows[(i - 1) * size: i * size]
    print(f"# {subject} topic {topic}: {len(rows)} questions total; part {i}/{n} = rows {(i-1)*size+1}-{(i-1)*size+len(chunk)}")
    print("# id | marks | qtype | ALL subtopics (primary first) | flags | text")
    cur = None
    for key, e, q in chunk:
        if key != cur:
            cur = key
            print(f"\n=== {key}")
        txt = clip(q.get("text_clean") or q.get("text"), 260).replace("\n", " / ")
        fl = ",".join(f for f in (q.get("flags") or []) if f in ("topic-uncertain", "key-disputed", "crop-bad", "parts-removed"))
        print(f"{q['id']} | {q.get('marks')} | {q.get('qtype')} | {' '.join(q.get('subtopics') or [])} | {fl} | {txt}")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    cmd, arg = sys.argv[1], sys.argv[2]
    part = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--part=")), "1/1")
    {"exam": lambda: exam(arg, "--full" in sys.argv), "taxonomy": lambda: taxonomy(arg), "guide": lambda: guide(arg),
     "reports": lambda: reports(arg), "audit": lambda: audit(arg, sys.argv[3], part)}[cmd]()
