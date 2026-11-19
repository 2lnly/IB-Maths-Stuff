#!/usr/bin/env python3
"""Segment one exam into per-question images/text. See db/SCHEMA.md "Segmenter contract".

    python3 pipeline/segment.py --exam-id physics-2018-M-P2-TZ1
    python3 pipeline/segment.py --exam-id math-2015-M-P1-TZ1 --out .scratch/x --overrides o.json
    python3 pipeline/segment.py --all [--subject math] [--jobs 32]     # whole catalog

Dispatches to pipeline/seg_<subject>.py, each of which exposes:

    segment(exam: dict, out_dir: pathlib.Path, overrides: dict | None) -> dict   # returns exam.json content

`exam` is the catalog entry (db/catalog.json). The subject module writes the images into out_dir;
this wrapper writes exam.json.
"""

import argparse
import importlib
import json
import sys
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))


def load_catalog():
    return {e["exam_id"]: e for e in json.loads((ROOT / "db" / "catalog.json").read_text())}


def run_one(exam: dict, out_dir: Path, overrides_path: Path | None = None) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    if overrides_path is None and (out_dir / "overrides.json").exists():
        overrides_path = out_dir / "overrides.json"
    overrides = json.loads(overrides_path.read_text()) if overrides_path else None

    mod = importlib.import_module(f"seg_{exam['subject']}")
    result = mod.segment(exam, out_dir, overrides)

    # remove stale images from earlier runs that are no longer referenced
    keep = set()
    for q in result.get("questions", []):
        keep.update(x for x in (q.get("image"), q.get("ms_image")) if x)
    for f in out_dir.glob("*.webp"):
        if f.name not in keep:
            f.unlink()

    from labels import merge_labels, write_json_atomic  # keeps classifier labels across re-segmentation
    result = merge_labels(result, out_dir)
    write_json_atomic(out_dir / "exam.json", result)
    return result


def _worker(exam_id: str, out: str):
    exam = load_catalog()[exam_id]
    try:
        r = run_one(exam, Path(out))
        return exam_id, r.get("status"), len(r.get("questions", [])), None
    except Exception:
        return exam_id, "failed", 0, traceback.format_exc(limit=3)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--exam-id")
    ap.add_argument("--out")
    ap.add_argument("--overrides")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--subject")
    ap.add_argument("--jobs", type=int, default=32)
    a = ap.parse_args()

    cat = load_catalog()
    if a.all:
        ids = [i for i, e in cat.items() if not a.subject or e["subject"] == a.subject]
        with ProcessPoolExecutor(a.jobs) as pool:
            futs = [pool.submit(_worker, i, str(ROOT / "db" / "exams" / i)) for i in ids]
            for f in as_completed(futs):
                eid, status, n, err = f.result()
                print(f"{status:8s} {n:3d}q  {eid}" + (f"\n{err}" if err else ""), flush=True)
        return

    if not a.exam_id or a.exam_id not in cat:
        sys.exit(f"unknown --exam-id {a.exam_id!r}")
    out = Path(a.out) if a.out else ROOT / "db" / "exams" / a.exam_id
    r = run_one(cat[a.exam_id], out, Path(a.overrides) if a.overrides else None)
    qs = r.get("questions", [])
    print(f"{r.get('status')}: {len(qs)} questions -> {out}")
    for q in qs:
        print(f"  q{q['num']:>4}  marks={q.get('marks')!s:>4}  ms={'y' if (q.get('ms_image') or q.get('mcq_answer')) else '-'}  "
              f"{','.join(q.get('flags', []))}")


if __name__ == "__main__":
    main()
