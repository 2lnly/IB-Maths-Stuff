#!/usr/bin/env python3
"""Build the static question database site.

Input (format: db/SCHEMA.md)
    <db>/catalog.json, <db>/taxonomy.json, <db>/exams/<exam_id>/exam.json (+ question images)

Output (<out>, default dist/)
    index.html, app.js, app.css,         copied from site/ (build id substituted for cache busting;
    richtext.js, vendor/katex/           vendor/ is copied byte for byte: pinned KaTeX, see its README.txt)
    data/index.json                      subject list, syllabuses, counts, build id
    data/<subject>.json                  taxonomy, exams and questions (compact keys)
                                         questions carry rn (reviewer note), xc (text is the checked transcription),
                                         dg/dr (duplicate group within the subject / preference rank in it)
    data/<subject>.text.json             question + markscheme text, only when the subject file
                                         would otherwise exceed --split-mb (loaded lazily by the site)
    img/<exam_id>/<image>                question and markscheme images (hard-linked when possible)

Usage
    python3 build.py [--db db/] [--out dist/] [--split-mb 15] [--no-images] [--strict] [--force]

Serve with any static file server, e.g.  python3 -m http.server -d dist
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

try:
    from PIL import Image
except ImportError:  # image sizes are optional
    Image = None

ROOT = Path(__file__).resolve().parent
SITE = ROOT / "site"
MARKER = ".question-db-build"

SUBJECT_NAMES = {"math": "Mathematics HL", "physics": "Physics HL", "economics": "Economics SL"}
SYLLABUS_NAMES = {
    "math-hl-legacy": "Mathematics HL (to 2020)",
    "math-aa-hl": "Mathematics: analysis and approaches HL (2021+)",
    "physics-legacy": "Physics HL (to 2024)",
    "physics-2023": "Physics HL (2025+)",
    "econ-legacy": "Economics SL (to 2021)",
    "econ-2020": "Economics SL (2022+)",
}
SYLLABUS_SHORT = {
    "math-hl-legacy": "HL to 2020", "math-aa-hl": "AA HL 2021+",
    "physics-legacy": "HL to 2024", "physics-2023": "HL 2025+",
    "econ-legacy": "SL to 2021", "econ-2020": "SL 2022+",
}
SESSIONS = {"May": "M", "November": "N"}
TZS = {"TZ1", "TZ2", "TZ3", None}
PAPERS = {"1", "1A", "1B", "2", "3"}
LEVELS = {"HL", "SL", "HLSL", None}
QTYPES = {"mcq", "short", "long", "essay", "data"}
ANSWER = {"ok", "missing", "suspect"}
STATUSES = {"done", "partial", "failed"}
MCQ = {"A", "B", "C", "D"}
ANSWER_RANK = {"ok": 0, "suspect": 1, "missing": 2}
MAX_FILES = 20000
MAX_FILE_BYTES = 25 * 1024 * 1024


class Log:
    def __init__(self, limit):
        self.limit = limit
        self.items = defaultdict(list)
        self.errors = 0

    def warn(self, kind, msg):
        self.items[kind].append(msg)

    def error(self, kind, msg):
        self.errors += 1
        self.items["ERROR " + kind].append(msg)

    def dump(self):
        if not self.items:
            print("\nNo validation warnings.")
            return
        print("\nValidation messages:")
        for kind in sorted(self.items):
            msgs = self.items[kind]
            print(f"  {kind}: {len(msgs)}")
            for m in msgs[: self.limit]:
                print(f"      {m}")
            if len(msgs) > self.limit:
                print(f"      ... {len(msgs) - self.limit} more")


def load_json(path, log, kind):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        log.error(kind, f"{path}: not found")
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        log.error(kind, f"{path}: invalid JSON ({e})")
    return None


def clean_str(v):
    if v is None:
        return None
    v = str(v).strip()
    return v or None


_PDF_PATH = re.compile(r"(?:~|/)[^\n\"']*?/([^/\n\"']+\.pdf)", re.I)
_HOME = re.compile(r"/(?:home|Users)/[^/\s\"']+")
_PNUM = re.compile(r"\bpaper number (\d{4}-\d{4})")
# catalogue bookkeeping that means nothing to a reader of the site
_INTERNAL_NOTE = re.compile(r"^(\d+ duplicate cop|duplicate |paper number |code |identity from |session from |"
                            r"time zone .* assigned)", re.I)
_CODE = re.compile(r"\bcode ([MN]\d\d/\d/[A-Z]+/[A-Z]+\d?[A-Z]?/[A-Z]+/TZ\d/[A-Z]+)")


def sanitize_notes(text):
    """Notes are free text from the pipeline; never publish local paths or user names."""
    text = clean_str(text)
    if not text:
        return None
    text = _PDF_PATH.sub(lambda m: m.group(1), text)
    text = _HOME.sub("~", text)
    return text


def public_notes(text):
    """Keep only the notes that describe the paper itself (scans, missing markscheme, identical papers...)."""
    text = clean_str(text)
    if not text:
        return None
    keep = [p.strip() for p in re.split(r";\s*", text) if p.strip() and not _INTERNAL_NOTE.match(p.strip())]
    return sanitize_notes("; ".join(keep))


def basename(p):
    p = clean_str(p)
    return os.path.basename(p.replace("\\", "/")) if p else None


def expected_exam_id(e):
    sess = SESSIONS.get(e.get("session"), "?")
    s = f"{e.get('subject')}-{e.get('year')}-{sess}-P{e.get('paper')}"
    if e.get("option"):
        s += "-" + re.sub(r"[^a-z0-9]+", "-", str(e["option"]).lower()).strip("-")
    if e.get("tz"):
        s += f"-{e['tz']}"
    return s


def natural_key(s):
    return [(0, int(t), "") if t.isdigit() else (1, 0, t) for t in re.findall(r"\d+|\D+", str(s or ""))]


def check_exam_fields(e, where, log, taxonomy):
    ok = True
    if not isinstance(e.get("exam_id"), str) or not e.get("exam_id"):
        log.error("exam-field", f"{where}: missing exam_id")
        return False
    eid = e["exam_id"]
    if not re.fullmatch(r"[A-Za-z0-9._-]+", eid):
        log.error("exam-field", f"{where}: exam_id {eid!r} has unsafe characters")
        return False
    if e.get("subject") not in taxonomy:
        log.warn("exam-subject", f"{eid}: subject {e.get('subject')!r} not in taxonomy.json")
    if not isinstance(e.get("year"), int):
        log.error("exam-field", f"{eid}: year must be an integer, got {e.get('year')!r}")
        ok = False
    if e.get("session") not in SESSIONS:
        log.error("exam-field", f"{eid}: session must be May|November, got {e.get('session')!r}")
        ok = False
    if e.get("tz") not in TZS:
        log.warn("exam-field", f"{eid}: unexpected tz {e.get('tz')!r}")
    if str(e.get("paper")) not in PAPERS:
        log.warn("exam-field", f"{eid}: unexpected paper {e.get('paper')!r}")
    if e.get("level") not in LEVELS:
        log.warn("exam-field", f"{eid}: unexpected level {e.get('level')!r}")
    if not e.get("syllabus"):
        log.warn("exam-field", f"{eid}: no syllabus")
    if ok and expected_exam_id(e) != eid:
        log.warn("exam-id-format", f"{eid}: fields suggest {expected_exam_id(e)}")
    return ok


# ---------------------------------------------------------------- duplicate questions
# Some papers were set in more than one time zone (or reused) verbatim. Two questions of the same subject in
# different exams are duplicates when their normalized transcription (text_clean) is equal, or when the text layer
# extracted from the PDF is equal (the same printed paper gives the same text even where two transcribers wrote
# the LaTeX differently). Questions whose content was removed are never matched; known marks or MCQ keys that
# disagree veto a match.
_DUP_QNUM = re.compile(r"^\s*\(?[A-Z]?\d{1,3}[a-z]?\s*[.)]\s*")
_DUP_DROP = re.compile(r"\\(?:left|right|displaystyle|textstyle|limits|quad|qquad|mathrm|textrm|text|textit|textbf|"
                       r"mathit|mathbf|boldsymbol|operatorname|mathsf|rm|it|bf)(?![A-Za-z])|\\[,;:! ]")
_DUP_CHARS = {"\u2212": "-", "\u2013": "-", "\u00d7": "\\times", "\u2264": "\\leq", "\u2265": "\\geq", "\u03b8": "\\theta",
              "\u03bb": "\\lambda", "\u03c0": "\\pi", "\u03bc": "\\mu", "\u03c9": "\\omega", "\u0394": "\\delta",
              "\u221a": "\\sqrt", "\u2192": "\\rightarrow", "\u00b0": "\\circ", "\u2018": "'", "\u2019": "'",
              "\u201c": '"', "\u201d": '"'}
_DUP_CHAR_RE = re.compile("|".join(re.escape(k) for k in _DUP_CHARS))


def dup_key(text):
    if not text:
        return ""
    t = unicodedata.normalize("NFKC", text)
    t = _DUP_QNUM.sub("", t)
    t = re.sub(r"\[[^\]]*\]", " ", t)                 # figure descriptions, mark allocations
    t = _DUP_CHAR_RE.sub(lambda m: _DUP_CHARS[m.group(0)], t)
    t = re.sub(r"\\[dt]frac", r"\\frac", t)
    t = re.sub(r"\\(le|ge)(?![a-z])", r"\\\1q", t)
    t = _DUP_DROP.sub("", t)
    return re.sub(r"[\s${}~]+", "", t).lower()


def find_duplicates(cands, log):
    """cands: dicts with qo, eid, clean, raw, marks, mcq, flags, rank. Sets qo['dg'], qo['dr']; returns groups."""
    parent = list(range(len(cands)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for field, min_len in (("clean", 40), ("raw", 60)):
        by = defaultdict(list)
        for i, c in enumerate(cands):
            k = c[field]
            if len(k) >= min_len:
                by[k].append(i)
        for idxs in by.values():
            for a, b in zip(idxs, idxs[1:]):
                ca, cb = cands[a], cands[b]
                if ca["eid"] == cb["eid"]:
                    log.warn("duplicate-same-exam", f"{ca['qo']['id']} and {cb['qo']['id']}: identical text in one exam")
                    continue
                if ca["marks"] is not None and cb["marks"] is not None and ca["marks"] != cb["marks"]:
                    log.warn("duplicate-vetoed", f"{ca['qo']['id']} / {cb['qo']['id']}: same text, marks "
                                                 f"{ca['marks']} vs {cb['marks']}")
                    continue
                if ca["mcq"] and cb["mcq"] and ca["mcq"] != cb["mcq"]:
                    log.warn("duplicate-vetoed", f"{ca['qo']['id']} / {cb['qo']['id']}: same text, MCQ key "
                                                 f"{ca['mcq']} vs {cb['mcq']}")
                    continue
                parent[find(a)] = find(b)
    groups = defaultdict(list)
    for i in range(len(cands)):
        groups[find(i)].append(cands[i])
    out = []
    for members in groups.values():
        if len(members) < 2:
            continue
        if len({m["eid"] for m in members}) < len(members):
            # two members from one exam: keep the group but log it (usually a segmentation problem)
            log.warn("duplicate-same-exam", "group with two questions of one exam: " + ", ".join(m["qo"]["id"] for m in members))
        members.sort(key=lambda m: m["rank"])
        out.append(members)
    out.sort(key=lambda ms: ms[0]["order"])
    for g, members in enumerate(out, 1):
        for r, m in enumerate(members):
            m["qo"]["dg"], m["qo"]["dr"] = g, r
    return out


def webp_size(path):
    """Read WebP dimensions from the header (VP8 / VP8L / VP8X) without Pillow."""
    with open(path, "rb") as f:
        h = f.read(30)
    if len(h) < 30 or h[:4] != b"RIFF" or h[8:12] != b"WEBP":
        return None
    kind = h[12:16]
    if kind == b"VP8 ":  # lossy: 14-bit width/height after the 3-byte start code
        return [int.from_bytes(h[26:28], "little") & 0x3FFF, int.from_bytes(h[28:30], "little") & 0x3FFF]
    if kind == b"VP8L":  # lossless: 14-bit (w-1), 14-bit (h-1) packed after signature byte 0x2f
        b = int.from_bytes(h[21:25], "little")
        return [(b & 0x3FFF) + 1, ((b >> 14) & 0x3FFF) + 1]
    if kind == b"VP8X":  # extended: 24-bit (w-1), (h-1)
        return [int.from_bytes(h[24:27], "little") + 1, int.from_bytes(h[27:30], "little") + 1]
    return None


def image_size(path):
    # Header parsing first: the Cloudflare build image has no Pillow.
    try:
        if str(path).lower().endswith(".webp"):
            size = webp_size(path)
            if size:
                return size
    except OSError:
        pass
    if Image is None:
        return None
    try:
        with Image.open(path) as im:
            return [im.width, im.height]
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=str(ROOT / "db"), help="database directory (default: db/)")
    ap.add_argument("--out", default=str(ROOT / "dist"), help="output directory (default: dist/)")
    ap.add_argument("--split-mb", type=float, default=15.0,
                    help="move text into data/<subject>.text.json when the subject file would exceed this size")
    ap.add_argument("--no-images", action="store_true", help="do not copy images (data only)")
    ap.add_argument("--strict", action="store_true", help="exit with status 1 if validation errors occur")
    ap.add_argument("--force", action="store_true",
                    help="replace --out even if it is not empty and was not produced by this script")
    ap.add_argument("--show", type=int, default=8, help="example messages to print per warning kind")
    args = ap.parse_args()

    db = Path(args.db).resolve()
    out = Path(args.out).resolve()
    log = Log(args.show)

    # ---------------------------------------------------------------- taxonomy
    taxonomy = load_json(db / "taxonomy.json", log, "taxonomy") or {}
    if not isinstance(taxonomy, dict):
        log.error("taxonomy", "taxonomy.json must be an object keyed by subject")
        taxonomy = {}
    topic_codes, sub_parent, tax_out = {}, {}, {}
    for subj, t in taxonomy.items():
        codes, sp, topics = set(), {}, []
        for tp in (t or {}).get("topics", []) or []:
            code = clean_str(tp.get("code"))
            if not code:
                log.error("taxonomy", f"{subj}: topic without code")
                continue
            if code in codes:
                log.error("taxonomy", f"{subj}: duplicate topic code {code}")
            codes.add(code)
            subs = []
            for st in tp.get("subtopics", []) or []:
                sc = clean_str(st.get("code"))
                if not sc:
                    log.error("taxonomy", f"{subj}/{code}: subtopic without code")
                    continue
                if sc in sp:
                    log.error("taxonomy", f"{subj}: duplicate subtopic code {sc}")
                sp[sc] = code
                subs.append({"c": sc, "n": clean_str(st.get("name")) or sc})
            topics.append({"c": code, "n": clean_str(tp.get("name")) or code, "s": subs})
        topic_codes[subj], sub_parent[subj], tax_out[subj] = codes, sp, topics

    # ---------------------------------------------------------------- catalog
    catalog = load_json(db / "catalog.json", log, "catalog")
    if catalog is None:
        catalog = []
    if not isinstance(catalog, list):
        log.error("catalog", "catalog.json must be an array")
        catalog = []
    exams = {}
    for i, e in enumerate(catalog):
        if not isinstance(e, dict):
            log.error("catalog", f"catalog[{i}] is not an object")
            continue
        if not check_exam_fields(e, f"catalog[{i}]", log, taxonomy):
            continue
        if e["exam_id"] in exams:
            log.error("catalog", f"duplicate exam_id {e['exam_id']}")
            continue
        exams[e["exam_id"]] = {"meta": e, "data": None, "dir": db / "exams" / e["exam_id"], "cat": True}

    # ---------------------------------------------------------------- exam files
    exam_dir = db / "exams"
    if exam_dir.is_dir():
        for d in sorted(exam_dir.iterdir()):
            f = d / "exam.json"
            if not f.is_file():
                continue
            data = load_json(f, log, "exam-json")
            if not isinstance(data, dict):
                continue
            eid = data.get("exam_id") or d.name
            if eid != d.name:
                log.warn("exam-json", f"{f}: exam_id {eid!r} differs from directory name; using directory")
                eid = d.name
            data["exam_id"] = eid
            if eid not in exams:
                log.warn("not-in-catalog", f"{eid}: exam.json present but not in catalog.json (included)")
                if not check_exam_fields(data, str(f), log, taxonomy):
                    continue
                exams[eid] = {"meta": data, "data": data, "dir": d}
            else:
                meta = exams[eid]["meta"]
                for k in ("subject", "syllabus", "year", "session", "tz", "paper", "option", "level"):
                    if k in data and data.get(k) != meta.get(k):
                        log.warn("catalog-mismatch", f"{eid}: {k} catalog={meta.get(k)!r} exam.json={data.get(k)!r}")
                exams[eid]["data"] = data
                exams[eid]["dir"] = d

    # ---------------------------------------------------------------- questions
    per_subject = defaultdict(lambda: {"exams": [], "questions": [], "text": {}, "dup": []})
    stats = defaultdict(Counter)
    seen_ids = set()
    images = []  # (src, dst)
    order = sorted(exams.values(), key=lambda x: (str(x["meta"]["subject"]), -x["meta"]["year"],
                                                   x["meta"]["session"] != "November", str(x["meta"]["paper"]),
                                                   str(x["meta"].get("option") or ""), str(x["meta"].get("tz") or "")))
    for ex in order:
        m, data = ex["meta"], ex["data"]
        subj, eid = m["subject"], m["exam_id"]
        S = per_subject[subj]
        st = stats[subj]
        st["exams"] += 1
        if ex.get("cat"):
            st["in_catalog"] += 1
        status = "unprocessed"
        if data is not None:
            status = data.get("status") if data.get("status") in STATUSES else None
            if status is None:
                log.warn("exam-status", f"{eid}: status {data.get('status')!r} invalid; treating as partial")
                status = "partial"
        st["exam_" + status] += 1
        raw_notes = " ; ".join(str(n) for n in (m.get("notes"), data.get("notes") if data else None) if n)
        code = _CODE.search(raw_notes)
        pnum = _PNUM.search(raw_notes)
        notes = "; ".join(n for n in (public_notes(m.get("notes")),
                                      public_notes(data.get("notes")) if data and data is not m else None) if n)
        ex_out = {
            "id": eid, "sy": m.get("syllabus"), "y": m["year"], "s": m["session"], "tz": m.get("tz"),
            "p": str(m.get("paper")), "o": m.get("option"), "l": m.get("level"), "st": status,
            "pg": data.get("qp_pages") if data else None,
            "ms": bool(clean_str(m.get("ms_pdf"))), "src": basename(m.get("qp_pdf")),
            "mss": basename(m.get("ms_pdf")), "cd": code.group(1) if code else None,
            "pn": pnum.group(1) if pnum else None,
            "nt": notes or None, "nq": 0, "mk": 0,
        }
        ex_out = {k: v for k, v in ex_out.items() if v is not None}
        e_index = len(S["exams"])
        S["exams"].append(ex_out)
        if data is None:
            continue
        qs = data.get("questions")
        if not isinstance(qs, list):
            if qs is not None:
                log.error("exam-json", f"{eid}: questions is not a list")
            qs = []
        if not qs and status == "done":
            log.warn("empty-exam", f"{eid}: status done but no questions")
        nums_seen = set()
        for qi, q in enumerate(qs):
            if not isinstance(q, dict):
                log.error("question", f"{eid}: questions[{qi}] is not an object")
                continue
            num = clean_str(q.get("num"))
            if num is None:
                log.error("question", f"{eid}: questions[{qi}] has no num")
                continue
            if num in nums_seen:
                log.warn("duplicate-num", f"{eid}: question number {num} appears twice")
            nums_seen.add(num)
            qid = clean_str(q.get("id")) or f"{eid}-q{num}"
            if qid != f"{eid}-q{num}":
                log.warn("question-id", f"{qid}: expected {eid}-q{num}")
            if qid in seen_ids:
                log.error("question-id", f"duplicate question id {qid} (skipped)")
                continue
            seen_ids.add(qid)

            qtype = q.get("qtype")
            if qtype not in QTYPES:
                log.warn("qtype", f"{qid}: qtype {qtype!r} invalid")
                qtype = None
            marks = q.get("marks")
            if marks is not None and not isinstance(marks, int):
                try:
                    marks = int(marks)
                except (TypeError, ValueError):
                    log.warn("marks", f"{qid}: marks {marks!r} not an integer")
                    marks = None
            section = clean_str(q.get("section"))

            topics, subtopics = [], []
            for c in q.get("topics") or []:
                c = clean_str(c)
                if c is None or c in topics:
                    continue
                if subj in topic_codes and c not in topic_codes[subj]:
                    log.warn("unknown-topic", f"{qid}: topic {c!r} not in taxonomy (dropped)")
                    continue
                topics.append(c)
            for c in q.get("subtopics") or []:
                c = clean_str(c)
                if c is None or c in subtopics:
                    continue
                parent = sub_parent.get(subj, {}).get(c)
                if parent is None:
                    log.warn("unknown-subtopic", f"{qid}: subtopic {c!r} not in taxonomy (dropped)")
                    continue
                if parent not in topics:
                    log.warn("subtopic-parent", f"{qid}: subtopic {c} without its topic {parent} (topic added)")
                    topics.append(parent)
                subtopics.append(c)

            def img(name, what):
                name = clean_str(name)
                if not name:
                    return None, None
                if "/" in name or "\\" in name or name.startswith("."):
                    log.error("image-name", f"{qid}: unsafe {what} name {name!r}")
                    return None, None
                src = ex["dir"] / name
                if not src.is_file():
                    log.warn("image-missing", f"{qid}: {what} {name} not found")
                    return None, None
                images.append((src, out / "img" / eid / name))
                return name, image_size(src)

            image, isize = img(q.get("image"), "image")
            ms_image, msize = img(q.get("ms_image"), "ms_image")
            # prefer the hand-checked transcription from labels.json (merged by pipeline/labels.py)
            text_clean, text_raw = clean_str(q.get("text_clean")), clean_str(q.get("text"))
            text = text_clean or text_raw
            ms_text = clean_str(q.get("ms_text"))
            mcq = clean_str(q.get("mcq_answer"))
            if mcq is not None:
                mcq = mcq.upper()
                if mcq not in MCQ:
                    log.warn("mcq-answer", f"{qid}: mcq_answer {mcq!r} invalid")
                    mcq = None
            if qtype == "mcq" and marks is None:
                marks = 1
            has_answer = bool(ms_image or ms_text or mcq)
            ans = q.get("answer_status")
            if ans not in ANSWER:
                if ans is not None:
                    log.warn("answer-status", f"{qid}: answer_status {ans!r} invalid")
                ans = "ok" if has_answer else "missing"
            if ans != "missing" and not has_answer:
                log.warn("answer-content", f"{qid}: answer_status {ans} but no markscheme content (set to missing)")
                ans = "missing"
            if qtype == "mcq" and not mcq and ans == "ok":
                log.warn("mcq-answer", f"{qid}: MCQ without mcq_answer")
            flags = []
            for f in q.get("flags") or []:
                f = clean_str(f)
                if f and f not in flags:
                    flags.append(f)
            note = sanitize_notes(q.get("review_note"))

            qo = {"id": qid, "e": e_index, "n": num, "sc": section, "m": marks, "t": qtype,
                  "im": image, "iz": isize, "ms": ms_image, "mz": msize, "a": mcq,
                  "tp": topics or None, "su": subtopics or None, "as": ans, "f": flags or None,
                  "rn": note, "xc": 1 if text_clean else None}
            qo = {k: v for k, v in qo.items() if v is not None}
            S["questions"].append(qo)
            if "parts-removed" not in flags:
                S["dup"].append({
                    "qo": qo, "eid": eid, "clean": dup_key(text_clean), "raw": dup_key(text_raw), "marks": marks,
                    "mcq": mcq, "order": len(S["questions"]),
                    # representative of a group: usable crop, markscheme, transcription, fewest flags, then paper order
                    "rank": ("crop-bad" in flags, ANSWER_RANK.get(ans, 3), not image, not text_clean, len(flags),
                             m["year"], m["session"] != "May", str(m.get("tz") or ""), eid),
                })
            S["text"][qid] = [text, ms_text]
            ex_out["nq"] += 1
            ex_out["mk"] += marks or 0

            st["questions"] += 1
            st["ans_" + ans] += 1
            if not topics:
                st["unclassified"] += 1
            elif not subtopics:
                st["no_subtopic"] += 1
            if len(topics) > 1:
                st["multi_topic"] += 1
            if not image:
                st["no_image"] += 1
            if not text:
                st["no_text"] += 1
            if text_clean:
                st["transcribed"] += 1
            if "parts-removed" in flags:
                st["removed"] += 1
            if "key-disputed" in flags:
                st["key_disputed"] += 1

    # ---------------------------------------------------------------- duplicates
    dup_groups = {}
    for subj, S in per_subject.items():
        groups = find_duplicates(S.pop("dup"), log)
        dup_groups[subj] = groups
        stats[subj]["dup_groups"] = len(groups)
        stats[subj]["repeats"] = sum(len(g) - 1 for g in groups)

    # ---------------------------------------------------------------- write output
    if out.exists():
        if not (out / MARKER).exists() and any(out.iterdir()) and not args.force:
            sys.exit(f"refusing to overwrite {out}: not empty and not a previous build (no {MARKER}); "
                     f"delete it or pass --force")
        shutil.rmtree(out)
    (out / "data").mkdir(parents=True)
    (out / MARKER).write_text("generated by build.py; safe to delete\n")

    subjects_index = []
    data_hash = hashlib.sha1()
    for subj in sorted(per_subject, key=lambda s: (list(SUBJECT_NAMES).index(s) if s in SUBJECT_NAMES else 99, s)):
        S = per_subject[subj]
        syls = []
        for e in S["exams"]:
            if e.get("sy") and e["sy"] not in syls:
                syls.append(e["sy"])
        syls.sort(key=lambda sy: min(e["y"] for e in S["exams"] if e.get("sy") == sy))
        body = {
            "subject": subj,
            "name": SUBJECT_NAMES.get(subj, subj.capitalize()),
            "syllabuses": [{"id": s, "name": SYLLABUS_NAMES.get(s, s), "short": SYLLABUS_SHORT.get(s, s)}
                           for s in syls],
            "taxonomy": tax_out.get(subj, []),
            "exams": S["exams"],
            "questions": S["questions"],
        }
        texts = {k: [v[0], v[1]] for k, v in S["text"].items() if v[0] or v[1]}
        inline = [dict(q, x=texts[q["id"]][0], y=texts[q["id"]][1]) if q["id"] in texts else q
                  for q in S["questions"]]
        inline = [{k: v for k, v in q.items() if v is not None} for q in inline]
        combined = json.dumps(dict(body, questions=inline), ensure_ascii=False, separators=(",", ":"))
        text_file = None
        if len(combined.encode("utf-8")) > args.split_mb * 1024 * 1024:
            text_file = f"{subj}.text.json"
            main_json = json.dumps(body, ensure_ascii=False, separators=(",", ":"))
            text_json = json.dumps(texts, ensure_ascii=False, separators=(",", ":"))
            (out / "data" / text_file).write_text(text_json, encoding="utf-8")
            data_hash.update(text_json.encode())
        else:
            main_json = combined
        (out / "data" / f"{subj}.json").write_text(main_json, encoding="utf-8")
        data_hash.update(main_json.encode())
        subjects_index.append({
            "id": subj, "name": body["name"], "file": f"{subj}.json", "text_file": text_file,
            "syllabuses": body["syllabuses"], "exams": len(S["exams"]),
            "extracted": sum(1 for e in S["exams"] if e["st"] != "unprocessed"), "questions": len(S["questions"]),
            "repeats": stats[subj]["repeats"],
            "years": [min((e["y"] for e in S["exams"]), default=None), max((e["y"] for e in S["exams"]), default=None)],
        })

    # images
    linked = copied = 0
    if not args.no_images:
        for src, dst in images:
            dst.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.link(src, dst)
                linked += 1
            except FileNotFoundError:
                log.warn("image-missing", f"{src}: disappeared during build")
            except OSError:
                try:
                    shutil.copy2(src, dst)
                    copied += 1
                except OSError as e:
                    log.warn("image-copy", f"{src}: {e}")

    # site files (build id substituted for cache busting)
    site_hash = hashlib.sha1()
    site_files = sorted(p for p in SITE.rglob("*") if p.is_file())
    for p in site_files:
        site_hash.update(p.read_bytes())
    build_id = hashlib.sha1(site_hash.digest() + data_hash.digest()).hexdigest()[:10]
    for p in site_files:
        dst = out / p.relative_to(SITE)
        dst.parent.mkdir(parents=True, exist_ok=True)
        if p.suffix in (".html", ".js", ".css") and "vendor" not in p.relative_to(SITE).parts:
            dst.write_text(p.read_text(encoding="utf-8").replace("__BUILD_ID__", build_id), encoding="utf-8")
        else:
            shutil.copy2(p, dst)
    (out / "data" / "index.json").write_text(json.dumps(
        {"version": 1, "build": build_id, "subjects": subjects_index}, ensure_ascii=False, indent=1), encoding="utf-8")

    # ---------------------------------------------------------------- summary
    log.dump()
    cols = [("in_catalog", "catalog"), ("segmented", "segmented"), ("exam_done", "done"),
            ("exam_partial", "partial"), ("exam_failed", "failed"), ("exam_unprocessed", "pending"),
            ("questions", "questions"), ("ans_missing", "no-answer"), ("ans_suspect", "suspect"),
            ("unclassified", "unclassified"), ("no_subtopic", "no-subtopic"), ("multi_topic", "multi-topic"),
            ("no_image", "no-image"), ("no_text", "no-text"), ("transcribed", "transcribed"),
            ("key_disputed", "key-disputed"), ("removed", "removed"), ("repeats", "repeats")]
    for subj, st in stats.items():
        st["segmented"] = st["exam_done"] + st["exam_partial"] + st["exam_failed"]
    print("\nSummary (catalog = exams in catalog.json; segmented = exams with a readable exam.json; "
          "pending = not yet segmented)")
    widths = [max(len(label), 5) + 2 for _, label in cols]
    print(f"  {'subject':<10}" + "".join(f"{label:>{w}}" for (_, label), w in zip(cols, widths)))
    total = Counter()
    for s in subjects_index:
        st = stats[s["id"]]
        total.update(st)
        print(f"  {s['id']:<10}" + "".join(f"{st[k]:>{w}}" for (k, _), w in zip(cols, widths))
              + ("   (text split)" if s["text_file"] else ""))
    print(f"  {'total':<10}" + "".join(f"{total[k]:>{w}}" for (k, _), w in zip(cols, widths)))
    pairs = Counter()
    for subj, groups in dup_groups.items():
        for g in groups:
            pairs[" = ".join(sorted({m["eid"] for m in g}))] += 1
    if pairs:
        print(f"\nDuplicate questions: {sum(len(g) for gs in dup_groups.values() for g in gs)} questions in "
              f"{sum(len(gs) for gs in dup_groups.values())} groups (repeats = questions beyond the first of each group)")
        for k, n in sorted(pairs.items(), key=lambda kv: (-kv[1], kv[0]))[: max(args.show, 12)]:
            print(f"  {n:>4}  {k}")
        if len(pairs) > max(args.show, 12):
            print(f"        ... {len(pairs) - max(args.show, 12)} more exam combinations")

    n_files, biggest = 0, (0, None)
    for p in out.rglob("*"):
        if p.is_file():
            n_files += 1
            sz = p.stat().st_size
            if sz > biggest[0]:
                biggest = (sz, p)
    print(f"\nOutput: {out}")
    print(f"  files: {n_files} (limit {MAX_FILES}); images linked {linked}, copied {copied}")
    if biggest[1]:
        print(f"  largest file: {biggest[1].relative_to(out)} {biggest[0] / 1048576:.1f} MB "
              f"(limit {MAX_FILE_BYTES // 1048576} MB)")
    print(f"  build id: {build_id}")
    if n_files > MAX_FILES:
        log.error("hosting", f"{n_files} files exceeds {MAX_FILES}")
        print(f"ERROR: {n_files} files exceeds hosting limit of {MAX_FILES}")
    if biggest[0] > MAX_FILE_BYTES:
        log.error("hosting", "file too large")
        print(f"ERROR: {biggest[1]} exceeds {MAX_FILE_BYTES // 1048576} MB")
    if log.errors:
        print(f"\n{log.errors} validation error(s).")
        if args.strict:
            sys.exit(1)


if __name__ == "__main__":
    main()
