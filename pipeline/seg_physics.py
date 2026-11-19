#!/usr/bin/env python3
"""Physics HL question segmenter.  See db/SCHEMA.md ("Segmenter contract").

    segment(exam: dict, out_dir: Path, overrides: dict | None) -> dict   # exam.json content

Handles every physics paper variant in the catalog:

  * legacy P1 (2010-2024) and new-syllabus P1A (2025+): 40 MCQs, several per page.  Each MCQ is cropped
    individually; the markscheme is an answer-key grid -> mcq_answer / ms_text = letter, ms_image = null.
  * legacy P2: 2010-2015 "Section A" (A1 data analysis + structured) / "Section B" (choice, "Part 1/2");
    printed numbers are "A1".."A6","B1".."B4" up to May 2013, plain "1".."10" from Nov 2013.
    2016-2024 P2 and 2025 P2: plain structured questions 1..N, no sections.
  * legacy P3: 2009 syllabus (2010-2015) options E-J (printed "E1","E2",.. until May 2013, continuous
    numbering from Nov 2013); 2016 syllabus (2016-2024) Section A (data/experimental, section = null)
    + options A-D with continuous numbering (section = option letter).
  * 2025 P1B: data-based structured questions.

Question numbers ("num") are exactly as printed ("7", "A1", "E3").  Question paper boundaries come from
bold numbers in the left question column; markscheme boundaries from the question labels in the
markscheme's left column (front-matter instruction lists are skipped by anchoring from the end).

Boundary refinement (pixel based, see snap_start / snap_end / find_tableheads): a cut placed at a question
label is moved up to the blank gap above the label row when the row's first line rises above the label
(stacked fractions, exponents, brackets), and moved down when the previous question's last line hangs
below it; markscheme crops end before the next table's header row / top border, include their own
closing table rule at the end of the document, and continuation pages skip repeated header rows
wherever they sit on the page.  Page numbers are only recognised centred ("– 3 –"), so axis labels and
exponents near the page foot are no longer mistaken for footers (crops are clamped to the footer line).

Image pipeline: each question region (list of (page, y0, y1) pieces) is rendered at 150 dpi grayscale,
running headers/footers/barcodes/"continued" notes/section headings/dotted answer lines/empty answer
boxes are painted white, then blank horizontal bands are collapsed (rows covered by images or vector
drawings are never collapsed) and the pieces are stitched vertically.

section: legacy P2 2010-2015 -> "A"/"B"; P3 -> option letter ("A".."D" 2016+, "E".."J" 2010-2015) and
null for the compulsory 2016+ P3 Section A (data/experimental, qtype "data"); everything else null.

Overrides (db/SCHEMA.md): {"questions":[{"num","qp":[[page,y0,y1],..],"ms":[[page,y0,y1],..]}],
"ms_offsets":{"skip_pages":N}, "drop":[nums], "mcq_answers":{num:letter}}.  Pages are 0-based PDF page
indices, y in PDF points from the top of the page as displayed (after /Rotate; the 2016-2017 landscape
markschemes are rotated pages).  A "questions" entry whose num was not detected is added as a new
question (ordered by its first qp region).  Extension: an entry may also carry "section".
Overridden regions still get header/footer/answer-line clean-up and blank-band collapsing.
"""
from __future__ import annotations

import hashlib
import os
import re
import subprocess
import tempfile
from pathlib import Path

import fitz  # PyMuPDF
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
OCR_CACHE = ROOT / ".scratch" / "seg_physics" / "ocr"

DPI = 150
SC = DPI / 72.0
WEBP_QUALITY = 80
MAX_IMG_H = 16000            # WebP hard limit is 16383 px
INK = 225                    # gray value below which a pixel counts as ink (light grid lines count)
GAP_MAX = 46                 # blank runs longer than this (px) are collapsed ...
GAP_KEEP = 26                # ... to this many px
PIECE_SEP = 18               # white px between stitched pieces
MARGIN = 8                   # white px around the final image

fitz.TOOLS.mupdf_display_errors(False)

# --------------------------------------------------------------------------------------------------
# text classification
# --------------------------------------------------------------------------------------------------

PAGENUM_RE = re.compile(r'^[–—\-]\s*\d{1,3}\s*([–—\-])?$')   # page number "– 3 –" (checked by is_pagenum)
HDR_RE = [re.compile(p, re.I) for p in (
    r'^[MN]\s?\d{2}\s?/\s?\d\s?/\s?PH',                # paper code M15/4/PHYSI/HP2/ENG/TZ1/XX(/M)
    r'^\d{4}\s*[–—\-]\s*\d{4}\s*M?$',                 # paper number 2215-6508
    r'^\d{2}EP\d{2}$',                                 # page barcode text 24EP03
    r'^Turn over$',
    r'^©\s*International Baccalaureate',
    r'^©\s*IBO\b',
    r'^\d{1,3}\s+pages$',
    r'[MN]\s?\d{2}\s?/\s?\d\s?/\s?PH[A-Z]*\s?/',          # code anywhere in a header line (OCR merges)
)]
NOTE_RE = re.compile(
    r'^\((This question|Question|Questions|Option|Section)\b[^)]*(continue|on page)[^)]*\)?$'
    r'|^End of (Option|Section|examination|paper)\b'
    r'|^\(?This question continues\b'
    r'|^\(?continued?s?\s*(\.{2,}|…)?\s*\)?$|^\(?Question\s+[A-J]?\d{1,2}\s+continued\.?\)?$', re.I)
HEADING_RE = re.compile(
    r'^Section\s+[AB]\s*$|^SECTION\s+[AB]\b|^Section\s+[AB]\s*[\[(]|^Option\s+[A-J]\s*[—–\-:]|^OPTION\s+[A-J]\b'
    r'|^Option\s+[A-J]\s*$|^This section consists of\b|^Answer (all|two|one|both|any)\b.*\b(question|option|section)'
    r'|^Answers must be written within', re.I)
SECTION_RE = re.compile(r'^Section\s+([AB])\b', re.I)
OPTION_RE = re.compile(r'^Option\s+([A-J])\b(?!\s*(continue|,))', re.I)
BLANKPAGE_RE = re.compile(r'Please do not write on this page|Answers written on this page|^Blank page$'
                          r'|will not be marked\.?$', re.I)
STOP_RE = re.compile(r'^(References:?|Acknowledg(e)?ments:?|Disclaimer:)', re.I)
TABLEHEAD_WORDS = {"question", "answers", "answer", "notes", "total", "marks", "mark", "question answers notes total"}
TABLEHEAD_WORDS_ROW = TABLEHEAD_WORDS | {"q"}     # 2025 markschemes head the label column "Q"
DOT_CHARS = set('.\x08�…·_‥ \t    ')
LABEL_PREFIX_RE = re.compile(r'^\(?([0-9]{1,2}|[ivx]{1,4}|[a-d])[\.:)]\s*')
MARK_RE = re.compile(r'^([A-J]?)(\d{1,2})\.(?=\s|$)')
MSLABEL_RE = re.compile(r'^([A-J]?\d{1,2})(\.?)(?=\s|$)')
QMARKS_RE = re.compile(r'^\[(\d{1,2})\]$')
COVER_TOTAL_RE = re.compile(r'\[(\d{2,3})\s*marks\]')


def is_dots(t: str, width: float = 999.0) -> bool:
    """Dotted answer line ('. . . .', or the 2016+ dotted-line font which extracts as '\x08' + U+FFFD
    runs).  Single unmappable glyphs (U+FFFD) are usually maths symbols, so a minimum length/width
    is required."""
    if width < 40:
        return False
    s = t.strip()
    s = LABEL_PREFIX_RE.sub('', s)
    core = [c for c in s if c not in ' \t    ']
    if len(core) < 8:
        return False
    bad = sum(1 for c in core if c not in DOT_CHARS and not (0xE000 <= ord(c) <= 0xF8FF))
    return bad == 0


class Line:
    __slots__ = ("x0", "y0", "x1", "y1", "text", "bold", "size", "spans", "kind", "horiz")

    def __init__(self, x0, y0, x1, y1, text, bold, size, spans, horiz=True):
        self.x0, self.y0, self.x1, self.y1 = x0, y0, x1, y1
        self.text, self.bold, self.size, self.spans = text, bold, size, spans
        self.kind = "body"
        self.horiz = horiz

    @property
    def yc(self):
        return (self.y0 + self.y1) / 2

    def rect(self):
        return (self.x0, self.y0, self.x1, self.y1)


class PageInfo:
    def __init__(self, pn, w, h):
        self.pn, self.w, self.h = pn, w, h
        self.lines: list[Line] = []
        self.images: list[tuple] = []        # display-space rects
        self.paths: list[tuple] = []         # display-space rects of vector paths (diagram parts)
        self.hsegs: list[tuple] = []         # (x0, x1, y)
        self.vsegs: list[tuple] = []         # (x, y0, y1)
        self.masks: list[tuple] = []         # rects painted white
        self.empty_boxes: list[tuple] = []
        self.soft_cols: list[tuple] = []     # (x, y0, y1) box edges ignored when finding blank rows
        self.blank = False
        self.ocr = False
        self.top = 0.0
        self.bottom = h
        self.xl = 0.0
        self.xr = w
        self.tablehead_y = None
        self.tableheads: list[tuple] = []    # (y_top, y_bottom) bands of markscheme table header rows


def is_pagenum(L: Line, w: float, h: float) -> bool:
    """Running page number "– 3 –".  Only a horizontally centred number counts, and in the bottom
    margin it needs both dashes: graph axis labels ("–20") and superscript exponents ("-1" of m s-1)
    near the page bottom also look like "–N" and must not be treated as footers (that clipped real
    content, since every crop is clamped to the footer line)."""
    m = PAGENUM_RE.match(L.text.strip())
    if not m or abs((L.x0 + L.x1) / 2 - w / 2) > 0.08 * w:
        return False
    return L.y1 < 0.11 * h or bool(m.group(1))


# --------------------------------------------------------------------------------------------------
# PDF loading
# --------------------------------------------------------------------------------------------------

def _is_bold(span) -> bool:
    return bool(span["flags"] & 16) or bool(re.search(r'Bold|Black|Heavy|,B\b|-B\b|Bd\b', span["font"]))


def _ocr_lines(doc_path: str, page, pn: int) -> list[Line]:
    """OCR a page without a text layer (tesseract TSV, cached under .scratch)."""
    OCR_CACHE.mkdir(parents=True, exist_ok=True)
    st = os.stat(doc_path)
    key = hashlib.sha1(f"psm6|{doc_path}|{st.st_size}|{int(st.st_mtime)}|{pn}".encode()).hexdigest()[:20]
    cache = OCR_CACHE / f"{key}.tsv"
    if not cache.exists():
        pix = page.get_pixmap(dpi=300, colorspace=fitz.csGRAY, alpha=False)
        with tempfile.TemporaryDirectory() as td:
            png = os.path.join(td, "p.png")
            pix.save(png)
            r = subprocess.run(["tesseract", png, "-", "--psm", "6", "tsv"], capture_output=True, text=True,
                               timeout=120)
        cache.write_text(r.stdout)
    rows = cache.read_text().splitlines()[1:]
    groups: dict[tuple, list] = {}
    for row in rows:
        f = row.split("\t")
        if len(f) < 12 or not f[11].strip():
            continue
        try:
            conf = float(f[10])
        except ValueError:
            continue
        if conf < 20:
            continue
        k = (int(f[2]), int(f[3]), int(f[4]))
        x, y, w, h = (int(v) / (300 / 72.0) for v in f[6:10])
        groups.setdefault(k, []).append((x, y, x + w, y + h, f[11]))
    out = []
    for ws in groups.values():
        ws.sort()
        x0 = min(w[0] for w in ws); y0 = min(w[1] for w in ws)
        x1 = max(w[2] for w in ws); y1 = max(w[3] for w in ws)
        text = " ".join(w[4] for w in ws)
        spans = [{"text": w[4], "bbox": w[:4], "bold": None, "size": w[3] - w[1]} for w in ws]
        out.append(Line(x0, y0, x1, y1, text, None, y1 - y0, spans))
    return out


def load_pdf(path: str, kind: str):
    """kind: 'qp' | 'ms'.  Returns (doc, [PageInfo])."""
    doc = fitz.open(path)
    pages = []
    for pn in range(doc.page_count):
        page = doc[pn]
        rm = page.rotation_matrix
        P = PageInfo(pn, page.rect.width, page.rect.height)
        d = page.get_text("dict", flags=fitz.TEXT_PRESERVE_LIGATURES | fitz.TEXT_PRESERVE_WHITESPACE
                          | fitz.TEXT_MEDIABOX_CLIP)
        n_chars = 0
        for b in d["blocks"]:
            if b.get("type") != 0:
                continue
            for l in b["lines"]:
                sp = [s for s in l["spans"] if s["text"].strip()]
                if not sp:
                    continue
                r = fitz.Rect(l["bbox"]) * rm
                dv = (fitz.Point(l["dir"]) * rm) - (fitz.Point(0, 0) * rm)
                horiz = abs(dv.y) < 0.2 and dv.x > 0
                spans = []
                for s in sp:
                    sr = fitz.Rect(s["bbox"]) * rm
                    spans.append({"text": s["text"], "bbox": (sr.x0, sr.y0, sr.x1, sr.y1),
                                  "bold": _is_bold(s), "size": s["size"]})
                text = "".join(s["text"] for s in l["spans"]).strip()
                n_chars += len(text)
                P.lines.append(Line(r.x0, r.y0, r.x1, r.y1, text, spans[0]["bold"], sp[0]["size"], spans, horiz))
        try:
            for im in page.get_image_info():
                r = fitz.Rect(im["bbox"]) * rm
                r &= page.rect
                if not r.is_empty and r.width > 2 and r.height > 2:
                    P.images.append((r.x0, r.y0, r.x1, r.y1))
        except Exception:
            pass
        if n_chars < 15 and P.images:
            # scanned page -> OCR
            try:
                P.lines = _ocr_lines(path, page, pn)
                P.ocr = True
            except Exception:
                P.lines = []
        if True:   # vector graphics: answer boxes, table rules, diagrams
            try:
                drw = page.get_drawings()
            except Exception:
                drw = []
            for path_ in drw:
                pr = fitz.Rect(path_["rect"]) * rm
                fill, col = path_.get("fill"), path_.get("color")
                white = lambda c: c is not None and len(c) >= 1 and min(c) > 0.93
                if (fill is None or white(fill)) and (col is None or white(col) or path_.get("type") == "f"):
                    continue        # invisible / white-out shapes
                only_segs = True
                for it in path_["items"]:
                    op = it[0]
                    if op == "l":
                        p1, p2 = it[1] * rm, it[2] * rm
                        if abs(p1.y - p2.y) < 1.0 and abs(p1.x - p2.x) > 1:
                            P.hsegs.append((min(p1.x, p2.x), max(p1.x, p2.x), (p1.y + p2.y) / 2))
                        elif abs(p1.x - p2.x) < 1.0 and abs(p1.y - p2.y) > 1:
                            P.vsegs.append(((p1.x + p2.x) / 2, min(p1.y, p2.y), max(p1.y, p2.y)))
                        else:
                            only_segs = False
                    elif op == "re":
                        rr = fitz.Rect(it[1]) * rm
                        if rr.height < 1.5 and rr.width > 1:
                            P.hsegs.append((rr.x0, rr.x1, (rr.y0 + rr.y1) / 2))
                        elif rr.width < 1.5 and rr.height > 1:
                            P.vsegs.append(((rr.x0 + rr.x1) / 2, rr.y0, rr.y1))
                        else:
                            only_segs = False
                            if path_.get("type") in ("s",) or not path_.get("fill"):
                                P.hsegs.append((rr.x0, rr.x1, rr.y0)); P.hsegs.append((rr.x0, rr.x1, rr.y1))
                                P.vsegs.append((rr.x0, rr.y0, rr.y1)); P.vsegs.append((rr.x1, rr.y0, rr.y1))
                    else:
                        only_segs = False
                if pr.width < 0.3 and pr.height < 0.3:
                    continue
                ops = [it[0] for it in path_["items"]]
                frame = (not path_.get("fill") and pr.width > 150 and pr.height > 30
                         and ((ops == ["re"]) or (len(ops) <= 8 and set(ops) <= {"l", "c"})))
                P.paths.append((pr.x0, pr.y0, pr.x1, pr.y1, only_segs, frame))
        pages.append(P)
    return doc, pages


# --------------------------------------------------------------------------------------------------
# page analysis
# --------------------------------------------------------------------------------------------------

def classify_page(P: PageInfo, kind: str, rend: "Renderer | None" = None):
    w, h = P.w, P.h
    top_hdr, bot_hdr = [], []
    for L in P.lines:
        t = L.text.strip()
        in_top = L.y1 < 0.11 * h
        in_bot = L.y0 > 0.86 * h
        if (in_top or in_bot) and (any(r.search(t) for r in HDR_RE) or is_pagenum(L, w, h)):
            L.kind = "header"
        elif kind == "qp" and L.y0 > 0.925 * h and re.fullmatch(r'[\d\s]{2,8}', t):
            L.kind = "header"    # barcode digits
        elif not L.horiz and (L.x0 < 0.06 * w or L.x1 > 0.94 * w):
            L.kind = "header"    # vertical text in the margins (rotated codes)
        elif NOTE_RE.search(t):
            L.kind = "note"
        elif BLANKPAGE_RE.search(t):
            L.kind = "blank"
        elif HEADING_RE.search(t) and (L.bold or L.bold is None or t.lower().startswith(("answer", "this section"))):
            L.kind = "heading"
        elif is_dots(t, L.x1 - L.x0):
            L.kind = "dots"
        if L.kind == "header":
            (top_hdr if L.y0 < h / 2 else bot_hdr).append(L)
    # wrapped continuation lines of instruction headings ("... answer boxes" / "provided.")
    heads = [L for L in P.lines if L.kind == "heading"]
    for Hd in heads:
        for L in P.lines:
            if L.kind == "body" and -4 < L.y0 - Hd.y1 < 4 and abs(L.x0 - Hd.x0) < 3 and len(L.text) < 60 \
                    and L.text[:1].islower() and Hd.text.lower().startswith(("answer", "this section")):
                L.kind = "heading"
    # markscheme table header row ("Question  Answers  Notes  Total")
    if kind == "ms":
        th = [L for L in P.lines if L.kind == "body" and L.y1 < 0.25 * h
              and L.text.strip().lower().rstrip(':') in TABLEHEAD_WORDS and (L.bold or L.bold is None)]
        if len(th) >= 2:
            for L in th:
                L.kind = "tablehead"
            P.tablehead_y = max(L.y1 for L in th) + 2
        find_tableheads(P)
    body = [L for L in P.lines if L.kind == "body"]
    blanks = [L for L in P.lines if L.kind == "blank"]
    if blanks and len([L for L in body if len(L.text) > 3]) <= 1 and not P.images:
        P.blank = True
    if blanks and len(body) <= 3:
        P.blank = True
    P.top = max([L.y1 for L in top_hdr] + [0.035 * h]) + 1
    P.bottom = min([L.y0 for L in bot_hdr] + [h - 0.012 * h]) - 1
    if kind == "qp" and w < h:
        P.top = max(P.top, 0.06 * h)
        P.bottom = min(P.bottom, 0.935 * h)
        # vector/raster barcodes and corner marks just above the footer line
        body_bot = max([L.y1 for L in P.lines if L.kind not in ("header",) and L.y1 < P.bottom] + [0])
        foot = [r[1] for r in list(P.images) + [p[:4] for p in P.paths]
                if r[1] > 0.915 * h and r[3] - r[1] < 0.06 * h and r[1] > body_bot]
        if foot:
            P.bottom = min(P.bottom, min(foot) - 1)
    # horizontal extent
    if kind == "qp" and abs(w - 595) < 3:
        P.xl, P.xr = 34.0, 562.0
    else:
        xs0 = [L.x0 for L in body] + [s[0] for s in P.hsegs if s[1] - s[0] > 0.4 * w and P.top < s[2] < P.bottom]
        xs1 = [L.x1 for L in body] + [s[1] for s in P.hsegs if s[1] - s[0] > 0.4 * w and P.top < s[2] < P.bottom]
        P.xl = max(0.0, min(xs0 + [0.07 * w]) - 6)
        P.xr = min(w, max(xs1 + [0.93 * w]) + 6)
    # masks: non-body lines
    for L in P.lines:
        if L.kind in ("header", "note", "heading", "blank", "dots", "tablehead"):
            P.masks.append((L.x0 - 1.5, L.y0 - 1, L.x1 + 1.5, L.y1 + 1))
    # images in header/footer zone (barcodes, logos)
    for r in P.images:
        if r[3] <= P.top + 2 or r[1] >= P.bottom - 2:
            P.masks.append(r)
    if kind == "qp" and abs(w - 595) < 3:
        # margin decorations (hatched strips, page frame lines) poke outside the content width
        lo, hi = P.xl - 4, P.xr + 4
        P.paths = [p for p in P.paths if p[0] >= lo and p[2] <= hi]
        P.hsegs = [s for s in P.hsegs if s[0] >= lo and s[1] <= hi]
        P.vsegs = [v for v in P.vsegs if lo <= v[0] <= hi]
    if kind == "qp":
        find_empty_boxes(P, rend)
        mask_lone_rules(P)
    else:
        # markscheme tables: long column rules must not stop blank-band collapse inside tall cells
        P.soft_cols = [(v[0], v[1], v[2]) for v in P.vsegs if v[2] - v[1] > 25]


def find_tableheads(P: PageInfo):
    """Markscheme table header rows anywhere on the page ("Question Answers Notes Total"; 2025: "Q ...
    Notes Total", not bold).  A new option/section/question table can start mid-page or below a heading,
    so the classic "top 25 %" test misses them and the previous question's crop ended with the next
    table's header row.  Sets P.tableheads (bands incl. the header's own rules), masks the words, and sets
    P.tablehead_y when the header is the first content of the page (continuation pages skip it)."""
    cand = [L for L in P.lines if L.kind in ("body", "tablehead") and L.horiz
            and L.text.strip().lower().rstrip(':') in TABLEHEAD_WORDS_ROW]
    rows = []
    for L in sorted(cand, key=lambda L: L.yc):
        if rows and abs(rows[-1][-1].yc - L.yc) < 3:
            rows[-1].append(L)
        else:
            rows.append([L])
    hs = [s for s in _merge_h(P.hsegs) if s[1] - s[0] > 0.3 * P.w]
    for r in rows:
        words = {L.text.strip().lower().rstrip(':') for L in r}
        strong = sum(1 for L in r if L.bold or L.bold is None)
        if not (len(r) >= 3 and len(words) >= 3 or strong >= 2 and len(words) >= 2):
            continue
        ty0, ty1 = min(L.y0 for L in r), max(L.y1 for L in r)
        above = [s[2] for s in hs if ty0 - 10 <= s[2] <= ty0 + 1]
        below = [s[2] for s in hs if ty1 - 1 <= s[2] <= ty1 + 10]
        band = ((max(above) - 1.5) if above else ty0 - 2, (min(below) + 1.5) if below else ty1 + 2)
        P.tableheads.append(band)
        for L in r:
            L.kind = "tablehead"
        if P.tablehead_y is None and not any(L.kind == "body" and L.y1 < ty0 and L.y0 > P.top - 1
                                             for L in P.lines):
            P.tablehead_y = ty1 + 2


def mask_lone_rules(P: PageInfo):
    """Full-width horizontal rules with nothing near them (e.g. the end-of-paper rule)."""
    for s in P.hsegs:
        if s[1] - s[0] < 0.6 * P.w or not (P.top < s[2] < P.bottom):
            continue
        if any(b[1] - 4 <= s[2] <= b[3] + 4 and b[0] - 4 <= s[0] for b in P.empty_boxes):
            continue
        near = False
        for L in P.lines:
            if L.kind == "body" and L.y0 - 20 < s[2] < L.y1 + 20:
                near = True; break
        if not near:
            for p in P.paths:
                if p[1] - 15 < s[2] < p[3] + 15 and (p[3] - p[1]) > 3 and not (p[2] - p[0] > 0.6 * P.w and p[3] - p[1] < 3):
                    near = True; break
        if not near:
            for v in P.vsegs:
                if v[1] - 6 < s[2] < v[2] + 6 and s[0] - 6 < v[0] < s[1] + 6 and v[2] - v[1] > 3:
                    near = True; break
        if not near:
            P.masks.append((s[0] - 2, s[2] - 2, s[1] + 2, s[2] + 2))


def find_empty_boxes(P: PageInfo, rend=None):
    """Answer boxes (2016+ papers): two long horizontal rules joined by vertical edges, containing
    nothing but dotted lines.  They are painted white so the blank-band collapse removes them."""
    w = P.w
    H = sorted([s for s in _merge_h(P.hsegs) if s[1] - s[0] > 0.45 * w and P.top - 5 < s[2] < P.bottom + 5],
               key=lambda s: s[2])
    if len(H) < 2:
        return
    used = set()
    for i, a in enumerate(H):
        if i in used:
            continue
        for j in range(i + 1, len(H)):
            b = H[j]
            if b[2] - a[2] < 30:
                continue        # grid cells / table rows, not answer boxes
            if abs(b[0] - a[0]) > 5 or abs(b[1] - a[1]) > 5:
                continue
            hgt = b[2] - a[2]
            tol = min(14, 0.3 * hgt)
            left = any(abs(v[0] - a[0]) < 5 and v[1] <= a[2] + tol and v[2] >= b[2] - tol for v in P.vsegs)
            right = any(abs(v[0] - a[1]) < 5 and v[1] <= a[2] + tol and v[2] >= b[2] - tol for v in P.vsegs)
            if not (left or right):
                # rounded boxes: vertical edges may be part of curve paths -> accept path bbox match
                left = any(abs(p[0] - a[0]) < 5 and abs(p[2] - a[1]) < 5 and abs(p[1] - a[2]) < 5
                           and abs(p[3] - b[2]) < 5 for p in P.paths)
            if not (left or right):
                continue
            box = (min(a[0], b[0]), a[2], max(a[1], b[1]), b[2])
            kind = box_content(P, box, rend)
            if kind == "empty":
                P.empty_boxes.append(box)
                P.masks.append((box[0] - 3, box[1] - 3, box[2] + 3, box[3] + 3))
                used.add(j)
            elif kind == "text":
                # answer box with printed labels only: its side edges must not stop blank-band collapse
                P.soft_cols.append((box[0], box[1], box[3]))
                P.soft_cols.append((box[2], box[1], box[3]))
                used.add(j)
            break


def _merge_h(segs, gap=3.0):
    """Join collinear touching horizontal segments (box edges are often drawn in pieces)."""
    out = []
    for s in sorted(segs, key=lambda s: (round(s[2]), s[0])):
        if out and abs(out[-1][2] - s[2]) < 1.0 and s[0] <= out[-1][1] + gap:
            o = out[-1]
            out[-1] = (o[0], max(o[1], s[1]), o[2])
        else:
            out.append(tuple(s))
    return out


def _inside(r, box, pad=0.0):
    return r[0] >= box[0] - pad and r[2] <= box[2] + pad and r[1] >= box[1] - pad and r[3] <= box[3] + pad


def _overlap(r, box):
    return not (r[2] <= box[0] or r[0] >= box[2] or r[3] <= box[1] or r[1] >= box[3])


def box_content(P: PageInfo, box, rend=None) -> str:
    """'empty' (only dotted lines / tiny labels), 'text' (printed text only) or 'graphic'."""
    inner = (box[0] + 4, box[1] + 3, box[2] - 4, box[3] - 3)
    for r in P.images:
        if _overlap(r, inner):
            return "graphic"
    for p in P.paths:
        if _overlap(p[:4], inner):
            # ignore the box's own edges / corners
            if (p[2] - p[0] < 1.5 or p[3] - p[1] < 1.5) or _near_edge(p, box):
                continue
            return "graphic"
    for s in P.hsegs:
        if box[0] + 6 < (s[0] + s[1]) / 2 < box[2] - 6 and box[1] + 4 < s[2] < box[3] - 4:
            return "graphic"
    for v in P.vsegs:
        if box[0] + 6 < v[0] < box[2] - 6 and v[2] > box[1] + 4 and v[1] < box[3] - 4:
            return "graphic"
    if rend is not None:
        # pixel test: anything inked (even light grey) inside the box that is not text?
        arr = rend.page(P.pn)
        X0, Y0 = int(inner[0] * SC), int(inner[1] * SC)
        X1, Y1 = int(inner[2] * SC), int(inner[3] * SC)
        if X1 - X0 > 4 and Y1 - Y0 > 4:
            sub = arr[Y0:Y1, X0:X1].copy()
            for L in P.lines:
                if _overlap(L.rect(), inner) and (L.kind == "dots" or re.search(r'[A-Za-z0-9]{2,}', L.text)
                                                  or re.fullmatch(r'\(?[0-9ivxa-d]{1,3}[\.:)]?', L.text.strip())):
                    a, b = int((L.y0 - 1) * SC) - Y0, int(np.ceil((L.y1 + 1) * SC)) - Y0
                    c, d = int((L.x0 - 1) * SC) - X0, int(np.ceil((L.x1 + 1) * SC)) - X0
                    sub[max(0, a):max(0, b), max(0, c):max(0, d)] = 255
            if int((sub < 235).sum()) > 25:
                return "graphic"
    for L in P.lines:
        if L.kind in ("dots",) or not _overlap(L.rect(), inner):
            continue
        t = L.text.strip()
        if L.kind == "body" and len(t) <= 4 and re.fullmatch(r'\(?[0-9ivxa-d]{1,3}[\.:)]?', t):
            continue    # "1:" / "(i)" labels inside answer boxes
        return "text"
    return "empty"


def _near_edge(p, box, tol=12):
    x0, y0, x1, y1 = p[:4]
    near_v = min(abs(x0 - box[0]), abs(x1 - box[2])) < tol and (x1 - x0) < tol * 1.5
    near_h = min(abs(y0 - box[1]), abs(y1 - box[3])) < tol and (y1 - y0) < tol * 1.5
    whole = abs(x0 - box[0]) < 5 and abs(x1 - box[2]) < 5 and abs(y0 - box[1]) < 5 and abs(y1 - box[3]) < 5
    return near_v or near_h or whole


# --------------------------------------------------------------------------------------------------
# rendering
# --------------------------------------------------------------------------------------------------

class Renderer:
    def __init__(self, doc, pages):
        self.doc, self.pages = doc, pages
        self.cache = {}

    def page(self, pn) -> np.ndarray:
        if pn not in self.cache:
            pix = self.doc[pn].get_pixmap(matrix=fitz.Matrix(SC, SC), colorspace=fitz.csGRAY, alpha=False)
            a = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.stride)[:, :pix.width]
            self.cache[pn] = a
        return self.cache[pn]

    def piece(self, pn, y0, y1):
        """Return (img, protect_rows) for the region [y0,y1] of page pn (masks applied) or None."""
        P = self.pages[pn]
        y0 = max(y0, P.top)
        y1 = min(y1, P.bottom)
        if y1 - y0 < 3:
            return None
        arr = self.page(pn)
        H, W = arr.shape
        X0, X1 = int(round(P.xl * SC)), int(round(P.xr * SC))
        Y0, Y1 = int(round(y0 * SC)), int(round(y1 * SC))
        X0, X1 = max(0, X0), min(W, X1)
        Y0, Y1 = max(0, Y0), min(H, Y1)
        if Y1 - Y0 < 3 or X1 - X0 < 10:
            return None
        sub = arr[Y0:Y1, X0:X1].copy()
        for m in P.masks:
            mx0, my0 = int(m[0] * SC) - X0, int(m[1] * SC) - Y0
            mx1, my1 = int(np.ceil(m[2] * SC)) - X0, int(np.ceil(m[3] * SC)) - Y0
            if mx1 <= 0 or my1 <= 0 or mx0 >= sub.shape[1] or my0 >= sub.shape[0]:
                continue
            sub[max(0, my0):max(0, my1), max(0, mx0):max(0, mx1)] = 255
        if P.soft_cols:
            inkimg = sub.copy()
            for x, a, b in P.soft_cols:
                cx0, cx1 = int((x - 2) * SC) - X0, int(np.ceil((x + 2) * SC)) - X0
                ry0, ry1 = int((a - 2) * SC) - Y0, int(np.ceil((b + 2) * SC)) - Y0
                if cx1 <= 0 or cx0 >= sub.shape[1] or ry1 <= 0 or ry0 >= sub.shape[0]:
                    continue
                inkimg[max(0, ry0 + 4):max(0, ry1 - 4), max(0, cx0):max(0, cx1)] = 255
        else:
            inkimg = sub
        prot = np.zeros(sub.shape[0], dtype=bool)
        cw = P.xr - P.xl
        regions = list(P.images) + [p[:4] for p in P.paths
                                    if (not p[4] or (p[3] - p[1] > 3 and p[2] - p[0] > 3))
                                    and not (p[5] and p[2] - p[0] > 0.6 * cw)]   # wide empty frames = answer boxes
        for r in regions:
            if r[3] <= y0 or r[1] >= y1 or r[2] <= P.xl or r[0] >= P.xr:
                continue
            if any(_inside(r, m, 3) for m in P.masks):
                continue
            # page-sized frames / rules are not diagrams
            if (r[2] - r[0]) > 0.9 * (P.xr - P.xl) and (r[3] - r[1]) > 0.5 * (P.bottom - P.top):
                continue
            a, b = int(r[1] * SC) - Y0, int(np.ceil(r[3] * SC)) - Y0
            prot[max(0, a):max(0, min(len(prot), b))] = True
        return sub, prot, inkimg


def compact(sub: np.ndarray, prot: np.ndarray, inkimg: np.ndarray | None = None) -> np.ndarray | None:
    ink = ((sub if inkimg is None else inkimg) < INK).sum(axis=1) > 0
    if not ink.any():
        return None
    rows = np.nonzero(ink)[0]
    a, b = rows[0], rows[-1] + 1
    sub, ink, prot = sub[a:b], ink[a:b], prot[a:b]
    keep = np.ones(len(ink), dtype=bool)
    i, n = 0, len(ink)
    while i < n:
        if ink[i]:
            i += 1
            continue
        j = i
        while j < n and not ink[j]:
            j += 1
        # blank run [i, j)
        if j - i > GAP_MAX and not prot[i:j].any():
            keep[i + GAP_KEEP // 2: j - (GAP_KEEP - GAP_KEEP // 2)] = False
        elif j - i > GAP_MAX:
            # partially protected run: collapse only the unprotected stretches
            k = i
            while k < j:
                if prot[k]:
                    k += 1
                    continue
                m = k
                while m < j and not prot[m]:
                    m += 1
                if m - k > GAP_MAX:
                    keep[k + GAP_KEEP // 2: m - (GAP_KEEP - GAP_KEEP // 2)] = False
                k = m
        i = j
    out = sub[keep]
    # trim fully white columns? keep full content width (consistent layout); only rows are trimmed
    return out


def stitch(parts: list[np.ndarray]) -> np.ndarray | None:
    parts = [p for p in parts if p is not None and p.size]
    if not parts:
        return None
    W = max(p.shape[1] for p in parts) + 2 * MARGIN
    Ht = sum(p.shape[0] for p in parts) + PIECE_SEP * (len(parts) - 1) + 2 * MARGIN
    out = np.full((Ht, W), 255, dtype=np.uint8)
    y = MARGIN
    for p in parts:
        out[y:y + p.shape[0], MARGIN:MARGIN + p.shape[1]] = p
        y += p.shape[0] + PIECE_SEP
    return out


def save_webp(arr: np.ndarray, path: Path) -> bool:
    """Returns True if the image had to be downscaled."""
    im = Image.fromarray(arr, mode="L")
    scaled = False
    if im.height > MAX_IMG_H:
        f = MAX_IMG_H / im.height
        im = im.resize((max(1, int(im.width * f)), MAX_IMG_H), Image.LANCZOS)
        scaled = True
    im.save(path, "WEBP", quality=WEBP_QUALITY, method=4)
    return scaled


# --------------------------------------------------------------------------------------------------
# regions -> image/text
# --------------------------------------------------------------------------------------------------

def _has_content(P, y0, y1, need_text=False):
    for L in P.lines:
        if L.kind == "body" and y0 - 1 <= L.yc <= y1 + 1 and L.x1 > P.xl and L.x0 < P.xr:
            return True
    for r in P.images:
        if r[1] < y1 and r[3] > y0 and r[1] >= P.top - 2 and r[3] <= P.bottom + 2:
            return True
    if need_text:
        return False
    for p in P.paths:
        if p[1] < y1 and p[3] > y0 and p[2] > P.xl and p[0] < P.xr and p[1] >= P.top and p[3] <= P.bottom \
                and not any(_inside(p[:4], m, 3) for m in P.masks):
            return True
    return False


def region_pieces(pages, start, end, ms=False):
    """start=(pn, y), end=(pn, y) exclusive.  Returns [(pn, y0, y1)] skipping blank/empty pages."""
    out = []
    sp, sy = start
    ep, ey = end
    for pn in range(sp, ep + 1):
        if pn >= len(pages):
            break
        P = pages[pn]
        if P.blank:
            continue
        y0 = sy if pn == sp else P.top
        if ms and pn != sp and P.tablehead_y:
            y0 = max(y0, P.tablehead_y)     # skip the repeated "Question Answers Notes Total" row
        y1 = ey if pn == ep else P.bottom
        if ms and pn == ep:
            # the next question's table may open with its own header row right above its first row:
            # end before that header (and its rules) instead of carrying it at the bottom of this crop
            for bt, bb in P.tableheads:
                if y0 < bt and bb - 6 <= y1 <= bb + 12 and \
                        not any(L.kind == "body" and bb - 1 < L.yc < y1 for L in P.lines):
                    y1 = min(y1, bt)
        if y1 - y0 > 2 and _has_content(P, y0, y1, need_text=ms):
            out.append((pn, y0, y1))
    return out


# --------------------------------------------------------------------------------------------------
# boundary refinement (pixel based)
# --------------------------------------------------------------------------------------------------

MINGAP_PX = 3          # a blank run of >= this many px rows (150 dpi) separates two text rows
OVERHANG = 20.0        # how far (pt) above a question label its first line may reach (stacked fractions)


def band_ink(rend: "Renderer", P: PageInfo, y0: float, y1: float):
    """(Y0, ink px count per pixel row) for the band [y0, y1) of the content width: masks painted white,
    thin vertical rules (table / box edges) ignored so that table rows still show their blank padding."""
    arr = rend.page(P.pn)
    H, W = arr.shape
    X0, X1 = max(0, int(round(P.xl * SC))), min(W, int(round(P.xr * SC)))
    Y0, Y1 = max(0, int(round(y0 * SC))), min(H, int(round(y1 * SC)))
    if Y1 - Y0 < 1 or X1 - X0 < 10:
        return Y0, np.zeros(0, dtype=int)
    ink = arr[Y0:Y1, X0:X1] < INK
    rects = list(P.masks) + [(v[0] - 1.2, v[1] - 1, v[0] + 1.2, v[2] + 1) for v in P.vsegs] + \
        [(p[0] - 0.7, p[1] - 1, p[2] + 0.7, p[3] + 1) for p in P.paths if p[2] - p[0] < 1.6 and p[3] - p[1] > 4]
    for m in rects:
        mx0, my0 = int(m[0] * SC) - X0, int(m[1] * SC) - Y0
        mx1, my1 = int(np.ceil(m[2] * SC)) - X0, int(np.ceil(m[3] * SC)) - Y0
        if mx1 <= 0 or my1 <= 0 or mx0 >= ink.shape[1] or my0 >= ink.shape[0]:
            continue
        ink[max(0, my0):max(0, my1), max(0, mx0):max(0, mx1)] = False
    if ink.shape[0] >= 12:
        ink[:, ink.mean(axis=0) > 0.85] = False      # undeclared vertical rules
    return Y0, ink.sum(axis=1)


def _table_top_rule(P: PageInfo, cnt, Y0: int, j: int):
    """Row j (pixel index into cnt) is the ink just above the blank gap over a markscheme label.  If it
    is a lone horizontal table rule with free space above it and no column rule rising above it, it is
    the top border of the table this question starts (not a border shared with the previous question's
    rows): return a cut just above it, so the previous crop does not end with that border (and its
    column-rule stubs).  Otherwise None."""
    if j < 0:
        return None
    ink = cnt > 0
    k = j
    while k >= 0 and ink[k]:
        k -= 1
    if j - k > 3 or max(cnt[k + 1:j + 1]) < 0.5 * (P.xr - P.xl) * SC:
        return None
    m = k
    while m >= 0 and not ink[m]:
        m -= 1
    if m >= 0 and k - m < 2 * MINGAP_PX:
        return None
    top, bot = (Y0 + k + 1) / SC, (Y0 + j + 1) / SC
    if not any(abs(sg[2] - (top + bot) / 2) < 2 and sg[1] - sg[0] > 0.3 * (P.xr - P.xl) for sg in _merge_h(P.hsegs)):
        return None
    if any(v[1] < top - 2 and v[2] > top - 0.5 and P.xl - 2 <= v[0] <= P.xr + 2 for v in P.vsegs) or \
            any(p[2] - p[0] < 1.6 and p[1] < top - 2 and p[3] > top - 0.5 for p in P.paths):
        return None
    return top - min(2.0, (k - m) / SC / 2)


def snap_start(rend, P: PageInfo, cut: float, L: Line, end_cut: float | None = None,
               table_rule: bool = False) -> tuple[float, float]:
    """Boundary above a question whose number/label is line L: returns (start of this question, end of
    the previous one), given the label-based values (cut, end_cut; end_cut defaults to cut).

    A first line with a stacked fraction, bracket or exponent rises above the label's own box, so a cut
    at the label slices it: the top went to the previous question and was clipped from this one (the
    most frequent reviewer fix).  Starting inside the label row's ink, walk up through ink (bridging
    hair gaps) to the first real blank gap and cut there.  Ink above the cut that is separated from the
    label row by such a gap is the previous question's and is handed back to it.  The label-based cut is
    kept whenever it already lies in that gap (or no gap is found within reach)."""
    end_cut = cut if end_cut is None else end_cut
    keep = (cut, end_cut)
    lo = max(P.top, L.y0 - OVERHANG)
    Y0, cnt = band_ink(rend, P, lo, L.y1)
    ink = cnt > 0
    n = len(ink)
    if n < 4:
        return keep
    i = min(n - 1, int(L.yc * SC) - Y0)
    while i >= 0 and not ink[i] and (Y0 + i) / SC > L.y0:
        i -= 1
    if i < 0 or not ink[i]:
        return keep
    while True:
        while i >= 0 and ink[i]:
            i -= 1
        if i < 0:
            # label row ink reaches the top of the window: only the page top can bound it
            return (lo, lo) if lo <= P.top + 0.01 and cut > lo else keep
        j = i
        while j >= 0 and not ink[j]:
            j -= 1
        if i - j >= MINGAP_PX or j < 0:
            break
        i = j
    gap_top, gap_bot = (Y0 + j + 1) / SC, (Y0 + i + 1) / SC
    if gap_top - 0.5 <= cut <= gap_bot:
        r = _table_top_rule(P, cnt, Y0, j) if table_rule else None
        if r is not None:
            return r, r
        return cut, min(end_cut, gap_bot)
    if cut < gap_top:
        # cut above the gap: hand the ink below the cut back to the previous question only when it is
        # the tail of a text line that starts above the cut (descenders of its last line), never a
        # table rule or a detached accent / overbar of this question's first line
        a = max(0, int(round(cut * SC)) - Y0)
        if j < 0 or not any(0 < c < 0.5 * (P.xr - P.xl) * SC for c in cnt[a:j + 1]) or \
                not any(M.kind == "body" and M.yc < cut < M.y1 and M.x1 > P.xl and M.x0 < P.xr for M in P.lines):
            return keep
    c = max(gap_top, gap_bot - 1.5)
    return c, c


def snap_end(rend, P: PageInfo, y: float, ms: bool) -> float:
    """End of the last question of a document: extend through ink that the text boxes under-measure
    (stacked denominators), and on markschemes include the closing rule of the answer table."""
    Y0, cnt = band_ink(rend, P, y - 1, min(P.bottom, y + 15))
    ink = cnt > 0
    if len(ink):
        i = int(round(1 * SC))
        k = i
        while k < len(ink) and ink[k]:
            k += 1
        if k < len(ink) and k > i:
            y = max(y, (Y0 + k) / SC + 0.5)
    if ms:
        hs = [s for s in _merge_h(P.hsegs) if s[1] - s[0] > 0.3 * (P.xr - P.xl) and y - 2 <= s[2] <= y + 12]
        for s in sorted(hs, key=lambda s: s[2]):
            if any(abs(v[2] - s[2]) < 2.5 and v[2] - v[1] > 8 for v in P.vsegs) and \
                    not any(L.kind == "body" and y - 1 < L.yc < s[2] for L in P.lines):
                y = max(y, s[2] + 1.5)
                break
    return min(y, P.bottom)


def region_text(pages, pieces) -> str:
    rows = []
    for pn, y0, y1 in pieces:
        P = pages[pn]
        ls = [L for L in P.lines if L.kind == "body" and y0 - 1 <= L.yc <= y1 + 1 and L.x1 > P.xl and L.x0 < P.xr]
        ls.sort(key=lambda L: (L.y0, L.x0))
        cur, ry0, ry1 = [], None, None
        for L in ls:
            if cur and not (ry0 - 1 <= L.yc <= ry1 + 1 or abs(L.yc - (ry0 + ry1) / 2) <= 3.5):
                rows.append("  ".join(x.text for x in sorted(cur, key=lambda z: z.x0)))
                cur = []
            if not cur:
                ry0, ry1 = L.y0, L.y1
            cur.append(L)
        if cur:
            rows.append("  ".join(x.text for x in sorted(cur, key=lambda z: z.x0)))
    txt = "\n".join(r for r in rows if r.strip())
    return re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f�]', '', txt).strip()


def region_marks(pages, pieces):
    tot, found = 0, False
    for pn, y0, y1 in pieces:
        P = pages[pn]
        for L in P.lines:
            if L.kind != "body" or not (y0 - 1 <= L.yc <= y1 + 1):
                continue
            for s in L.spans:
                st = s["text"].strip()
                m = QMARKS_RE.match(st)
                if m and s["bbox"][0] > 0.72 * P.w:
                    tot += int(m.group(1)); found = True
                    continue
                m = re.search(r'(?:^|[^\w\]\[])\[(\d{1,2})\]$', st)
                if m and s["bbox"][2] > 0.86 * P.w:
                    tot += int(m.group(1)); found = True
    return tot if found else None


def region_diagram_fraction(pages, pieces):
    area = 0.0; tot = 0.0
    for pn, y0, y1 in pieces:
        P = pages[pn]
        tot += (P.xr - P.xl) * (y1 - y0)
        rs = list(P.images) + [p[:4] for p in P.paths if not any(_inside(p[:4], m, 3) for m in P.masks)]
        ys = np.zeros(int(y1 - y0) + 2, dtype=bool)
        for r in rs:
            if r[3] <= y0 or r[1] >= y1 or (r[2] - r[0]) < 8:
                continue
            ys[max(0, int(r[1] - y0)):max(0, int(r[3] - y0))] = True
        area += ys.sum() * (P.xr - P.xl)
    return area / tot if tot else 0.0


def render_region(rend: Renderer, pieces):
    parts = []
    for pn, y0, y1 in pieces:
        r = rend.piece(pn, y0, y1)
        if r is None:
            continue
        c = compact(*r)
        if c is not None and c.shape[0] > 4:
            parts.append(c)
    return stitch(parts)


# --------------------------------------------------------------------------------------------------
# question paper structure
# --------------------------------------------------------------------------------------------------

def _num_key(num: str):
    m = re.match(r'^([A-J]?)(\d+)$', num)
    return (m.group(1), int(m.group(2))) if m else ("", 0)


def find_qp_markers(pages):
    cands = []
    for P in pages:
        if P.blank:
            continue
        for L in P.lines:
            if L.kind != "body" or not L.horiz:
                continue
            m = MARK_RE.match(L.text.strip())
            if not m or L.x0 > 0.16 * P.w:
                continue
            if L.bold is False:
                continue
            cands.append([P.pn, L.y0, L.x0, m.group(1) + m.group(2), L])
    if not cands:
        return []
    # question column = most common x (rounded) among candidates
    from collections import Counter
    cx = Counter(round(c[2]) for c in cands)
    col = max(cx.items(), key=lambda kv: (kv[1], -kv[0]))[0]
    cands = [c for c in cands if abs(c[2] - col) <= 4.5]
    cands.sort(key=lambda c: (c[0], c[1]))
    # longest consistent chain (DP)
    n = len(cands)
    keys = [_num_key(c[3]) for c in cands]
    best = [0.0] * n
    prev = [-1] * n
    for j in range(n):
        lj, nj = keys[j]
        best[j] = 1.0 - 0.6 * (nj - 1)
        for i in range(j):
            li, ni = keys[i]
            if lj == li and nj > ni:
                sc = best[i] + 1.0 - 0.6 * (nj - ni - 1)
            elif lj > li and li != "" and lj != "":
                sc = best[i] + 1.0 - 0.6 * (nj - 1)
            else:
                continue
            if sc > best[j]:
                best[j], prev[j] = sc, i
    j = max(range(n), key=lambda k: (best[k], -k))
    chain = []
    while j >= 0:
        chain.append(cands[j]); j = prev[j]
    chain.reverse()
    return chain


def section_info(pages, markers, exam):
    """Returns list of section values (one per marker)."""
    paper = exam["paper"]
    first = (markers[0][0], 0) if markers else (0, 0)
    events = []
    for P in pages:
        for L in P.lines:
            if L.kind != "heading" or (P.pn, L.y0) < first:
                continue
            t = L.text.strip()
            m = SECTION_RE.match(t)
            if m:
                events.append((P.pn, L.y0, "S", m.group(1).upper()))
            m = OPTION_RE.match(t)
            if m:
                events.append((P.pn, L.y0, "O", m.group(1).upper()))
    events.sort()
    out = []
    for mk in markers:
        sec, opt = None, None
        for e in events:
            if (e[0], e[1]) > (mk[0], mk[1]):
                break
            if e[2] == "S":
                sec, opt = e[3], None
            else:
                opt = e[3]
        pre = _num_key(mk[3])[0]
        if paper == "3":
            out.append(pre or opt)
        elif paper == "2":
            out.append(sec or (pre if pre in ("A", "B") else None))
        else:
            out.append(None)
    return out


def find_stop(pages, after):
    """First references/acknowledgements line after `after` (pn, y)."""
    for P in pages:
        if P.pn < after[0]:
            continue
        for L in sorted(P.lines, key=lambda L: L.y0):
            if L.kind == "body" and (P.pn, L.y0) > after and STOP_RE.match(L.text.strip()) and L.x0 < 0.2 * P.w:
                return (P.pn, L.y0 - 2)
    return None


def last_content(pages, from_pn):
    """End position after the last body content in the document."""
    for P in reversed(pages):
        if P.pn < from_pn:
            break
        if P.blank:
            continue
        ys = [L.y1 for L in P.lines if L.kind == "body" and P.top <= L.y0 <= P.bottom]
        ys += [r[3] for r in P.images if P.top <= r[1] < P.bottom and r not in P.masks]
        if ys:
            return (P.pn, min(P.bottom, max(ys) + 4))
    return (from_pn, pages[from_pn].bottom)


def cover_total(pages):
    for P in pages[:3]:
        for L in P.lines:
            m = COVER_TOTAL_RE.search(L.text)
            if m and 'maximum mark' in L.text.lower():
                return int(m.group(1))
    return None


# --------------------------------------------------------------------------------------------------
# markscheme
# --------------------------------------------------------------------------------------------------

def parse_mcq_key(doc, pages, skip=0):
    ans = {}
    for P in pages[skip:]:
        page = doc[P.pn]
        rm = page.rotation_matrix
        words = []
        if P.ocr:
            for L in P.lines:
                for s in L.spans:
                    words.append((*s["bbox"], s["text"]))
        else:
            for w in page.get_text("words"):
                r = fitz.Rect(w[:4]) * rm
                words.append((r.x0, r.y0, r.x1, r.y1, w[4]))
        for w in words:
            m = re.fullmatch(r'(\d{1,2})\.?', w[4])
            if not m:
                continue
            yc = (w[1] + w[3]) / 2
            right = [v for v in words if v[0] > w[2] - 0.5 and v[0] - w[2] < 70 and abs((v[1] + v[3]) / 2 - yc) < 3.5]
            if not right:
                continue
            right.sort(key=lambda v: v[0])
            tok = right[0][4].strip()
            mm = re.fullmatch(r'([A-D])(?:\s*(?:/|,|or|and|&)\s*([A-D]))*', tok)
            if mm and m.group(1) not in ans:
                # also grab a following "/B" style continuation
                seq = tok
                for v in right[1:3]:
                    if re.fullmatch(r'(/|or|and|&|,)?[A-D]?', v[4].strip()) and v[0] - right[0][2] < 25:
                        seq += v[4].strip()
                ans[m.group(1)] = seq
    return ans


def find_ms_starts(pages, nums, skip=0):
    """Map question num -> (pn, y) of its first markscheme row.

    Labels are anchored from the END of the document backwards (so numbered front-matter instruction
    lists are skipped), then each start is moved back to the first row of the contiguous run of rows
    carrying the same label (2016+ markschemes repeat the number on every row/page)."""
    allc = []
    for P in pages[skip:]:
        if P.pn == 0 and skip == 0 and len(pages) > 2:
            continue           # cover
        for L in P.lines:
            if L.kind != "body" or not L.horiz or L.x0 > 0.2 * P.w:
                continue
            m = MSLABEL_RE.match(L.text.strip())
            if not m:
                continue
            allc.append((P.pn, L.y0, L.x0, m.group(1).upper(), L))
    if not allc:
        return {}, {}
    allc.sort(key=lambda c: (c[0], c[1]))
    numset = set(nums)
    from collections import Counter
    later = [c for c in allc if c[3] in numset]
    cx = Counter(round(c[2]) for c in later[len(later) // 3:]) if later else Counter()
    col = cx.most_common(1)[0][0] if cx else None

    def run(cands, lo, hi, order):
        """backward anchoring of `order` within positions (lo, hi); returns {num: pos}"""
        labels = [c[3] for c in cands]
        pos = [(c[0], c[1]) for c in cands]
        res = {}
        limit = hi
        for num in reversed(order):
            idx = None
            for k in range(len(cands) - 1, -1, -1):
                if pos[k] < limit and pos[k] > lo and labels[k] == num:
                    idx = k
                    break
            if idx is None:
                continue
            k = idx
            for jj in range(idx - 1, -1, -1):
                if pos[jj] <= lo:
                    break
                if labels[jj] == num:
                    k = jj
                elif cands[jj][2] > cands[idx][2] + 8:
                    continue    # number-led answer text ("17 (±1.5) ºC") right of the label column
                else:
                    break
            res[num] = pos[k]
            limit = pos[k]
        return res

    INF = (10 ** 6, 0.0)
    colc = [c for c in allc if col is None or abs(c[2] - col) <= 8]
    starts = run(colc, (-1, 0.0), INF, nums)
    # second pass: labels printed off the main column (indented / misaligned rows)
    for i, num in enumerate(nums):
        if num in starts:
            continue
        lo = max([starts[n] for n in nums[:i] if n in starts], default=(-1, 0.0))
        hi = min([starts[n] for n in nums[i + 1:] if n in starts], default=INF)
        r = run(allc, lo, hi, [num])
        if num in r:
            starts[num] = r[num]
    lines = {(c[0], c[1]): c[4] for c in allc}
    return {k: (v[0], v[1] - 3) for k, v in starts.items()}, {k: lines[v] for k, v in starts.items()}


# --------------------------------------------------------------------------------------------------
# main entry
# --------------------------------------------------------------------------------------------------

def _qtype(exam, num, section, marks, idx_in_section, is_mcq):
    paper = exam["paper"]
    if is_mcq:
        return "mcq"
    if paper == "1B":
        return "data"
    # db/CLASSIFY.md: physics P2 questions and P3 option questions of more than ~8 marks are "long"
    if paper == "3":
        return "data" if section is None else ("long" if (marks or 0) > 8 else "short")
    if paper == "2":
        if section == "B":
            return "long"
        if section == "A" and idx_in_section == 0 and exam["year"] <= 2015:
            return "data"
        return "long" if (marks or 0) > 8 else "short"
    return "short"


def _ov_regions(spec):
    out = []
    for r in spec or []:
        pn, y0, y1 = int(r[0]), float(r[1]), float(r[2])
        out.append((pn, y0, y1))
    return out


def segment(exam: dict, out_dir: Path, overrides: dict | None) -> dict:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    ov = overrides or {}
    ov_q = {str(q["num"]): q for q in ov.get("questions", []) if "num" in q}
    drop = {str(x) for x in ov.get("drop", [])}
    ov_mcq = {str(k): str(v).strip().upper() for k, v in (ov.get("mcq_answers") or {}).items()}
    skip_ms = int((ov.get("ms_offsets") or {}).get("skip_pages", 0) or 0)

    notes = []
    result = dict(exam)
    is_mcq_paper = exam["paper"] in ("1", "1A")

    qdoc, qpages = load_pdf(exam["qp_pdf"], "qp")
    qrend = Renderer(qdoc, qpages)
    for P in qpages:
        classify_page(P, "qp", qrend)
    any_ocr_qp = any(P.ocr for P in qpages)

    markers = find_qp_markers(qpages)
    sections = section_info(qpages, markers, exam) if markers else []

    # ---- question regions (automatic) ----
    autos = []      # dicts: num, section, pieces, flags
    if markers:
        stop = find_stop(qpages, (markers[-1][0], markers[-1][1]))
        end_doc = stop or last_content(qpages, markers[-1][0])
        if not stop:
            end_doc = (end_doc[0], snap_end(qrend, qpages[end_doc[0]], end_doc[1], ms=False))
        # boundary above each question number: (start of this question, end of the previous one)
        cuts = [snap_start(qrend, qpages[mk[0]], mk[1] - 4, mk[4], mk[1] - 3) for mk in markers]
        for i, mk in enumerate(markers):
            st = (mk[0], cuts[i][0])
            en = (markers[i + 1][0], cuts[i + 1][1]) if i + 1 < len(markers) else end_doc
            pcs = region_pieces(qpages, st, en)
            flags = []
            # sequence gap -> boundary guess
            if i + 1 < len(markers):
                a, b = _num_key(mk[3]), _num_key(markers[i + 1][3])
                if (a[0] == b[0] and b[1] != a[1] + 1) or (a[0] != b[0] and b[1] != 1):
                    flags.append("crop-uncertain")
            if i > 0:
                a, b = _num_key(markers[i - 1][3]), _num_key(mk[3])
                if (a[0] == b[0] and b[1] != a[1] + 1) or (a[0] != b[0] and b[1] != 1):
                    flags.append("crop-uncertain")
            if is_mcq_paper and len({p[0] for p in pcs}) > 2:
                flags.append("crop-uncertain")
            autos.append({"num": mk[3], "section": sections[i], "pieces": pcs, "flags": sorted(set(flags)),
                          "ocr": any(qpages[p[0]].ocr for p in pcs)})
        first = _num_key(markers[0][3])
        if first[1] != 1:
            notes.append(f"first detected question is {markers[0][3]}")
            autos[0]["flags"] = sorted(set(autos[0]["flags"] + ["crop-uncertain"]))

    # overrides: replace / add questions
    by_num = {a["num"]: a for a in autos}
    for num, q in ov_q.items():
        if "qp" in q:
            pcs = _ov_regions(q["qp"])
            if num in by_num:
                by_num[num]["pieces"] = pcs
                by_num[num]["flags"] = [f for f in by_num[num]["flags"] if f != "crop-uncertain"]
                by_num[num]["override"] = True
            else:
                sec = q.get("section")
                a = {"num": num, "section": sec, "pieces": pcs, "flags": [], "override": True,
                     "ocr": any(qpages[p[0]].ocr for p in pcs if p[0] < len(qpages))}
                autos.append(a); by_num[num] = a
        if "section" in q and num in by_num:
            by_num[num]["section"] = q["section"]
    autos = [a for a in autos if a["num"] not in drop]
    autos.sort(key=lambda a: (a["pieces"][0][0], a["pieces"][0][1]) if a["pieces"] else (10 ** 6, 0))

    # ---- markscheme ----
    mcq_key = {}
    ms_starts = {}
    mdoc = mpages = mrend = None
    if exam.get("ms_pdf"):
        try:
            mdoc, mpages = load_pdf(exam["ms_pdf"], "ms")
            mrend = Renderer(mdoc, mpages)
            for P in mpages:
                classify_page(P, "ms", mrend)
            # consistent crop width across same-sized markscheme pages (pieces stitch aligned)
            groups = {}
            for P in mpages:
                if P.pn > 0 and not P.blank:
                    groups.setdefault((round(P.w), round(P.h)), []).append(P)
            for g in groups.values():
                xl = min(P.xl for P in g); xr = max(P.xr for P in g)
                for P in g:
                    P.xl, P.xr = xl, xr
        except Exception as e:  # pragma: no cover
            notes.append(f"markscheme unreadable: {e}")
            mdoc = None
    if mdoc is not None:
        nums = [a["num"] for a in autos]
        if is_mcq_paper:
            mcq_key = parse_mcq_key(mdoc, mpages, skip_ms)
        else:
            ms_starts, ms_labels = find_ms_starts(mpages, nums, skip_ms)
            for k, (pn, y) in list(ms_starts.items()):
                ms_starts[k] = (pn, snap_start(mrend, mpages[pn], y, ms_labels[k], table_rule=True)[0])
    mcq_key.update(ov_mcq)

    # ms regions
    ms_regions = {}
    if mdoc is not None and not is_mcq_paper:
        ordered = sorted(((v, k) for k, v in ms_starts.items()))
        ms_end_doc = last_content(mpages, ordered[-1][0][0]) if ordered else None
        if ms_end_doc:
            ms_end_doc = (ms_end_doc[0], snap_end(mrend, mpages[ms_end_doc[0]], ms_end_doc[1], ms=True))
        for i, (st, num) in enumerate(ordered):
            en = ordered[i + 1][0] if i + 1 < len(ordered) else ms_end_doc
            ms_regions[num] = region_pieces(mpages, st, en, ms=True)
    for num, q in ov_q.items():
        if "ms" in q and mdoc is not None:
            ms_regions[num] = _ov_regions(q["ms"])

    # ---- build questions ----
    questions = []
    sec_counter = {}
    for a in autos:
        num = a["num"]
        pcs = a["pieces"]
        flags = list(a["flags"])
        if a.get("ocr"):
            flags.append("text-ocr")
        img = render_region(qrend, pcs)
        if img is None:
            notes.append(f"q{num}: empty crop")
            flags.append("crop-uncertain")
            continue
        fname = f"q{num}.webp"
        if save_webp(img, out_dir / fname):
            flags.append("downscaled")
        text = region_text(qpages, pcs)
        marks = 1 if is_mcq_paper else region_marks(qpages, pcs)
        if not is_mcq_paper and marks is None and not a.get("override"):
            flags.append("crop-uncertain")
        sec = a["section"]
        idx = sec_counter.get(sec, 0)
        sec_counter[sec] = idx + 1
        qtype = _qtype(exam, num, sec, marks, idx, is_mcq_paper)
        try:
            if region_diagram_fraction(qpages, pcs) > 0.4:
                flags.append("diagram-heavy")
        except Exception:
            pass
        q = {
            "id": f"{exam['exam_id']}-q{num}",
            "num": num,
            "section": sec,
            "marks": marks,
            "qtype": qtype,
            "image": fname,
            "ms_image": None,
            "text": text,
            "ms_text": None,
            "mcq_answer": None,
            "topics": [],
            "subtopics": [],
            "answer_status": "missing",
            "flags": [],
        }
        if is_mcq_paper and num not in ms_regions:
            ans = mcq_key.get(num)
            if ans:
                letters = re.findall(r'[A-D]', ans)
                q["mcq_answer"] = letters[0]
                q["ms_text"] = ans
                q["answer_status"] = "ok" if len(letters) == 1 else "suspect"
                if len(letters) > 1:
                    flags.append("mcq-multiple-answers")
        else:
            pcs_ms = ms_regions.get(num)
            if pcs_ms:
                mimg = render_region(mrend, pcs_ms)
                if mimg is not None:
                    mname = f"q{num}_ms.webp"
                    if save_webp(mimg, out_dir / mname):
                        flags.append("downscaled")
                    q["ms_image"] = mname
                    q["ms_text"] = region_text(mpages, pcs_ms) or None
                    q["answer_status"] = "ok"
                    if any(mpages[p[0]].ocr for p in pcs_ms):
                        flags.append("text-ocr")
            if is_mcq_paper and mcq_key.get(num):
                letters = re.findall(r'[A-D]', mcq_key[num])
                q["mcq_answer"] = letters[0] if letters else None
                q["ms_text"] = mcq_key[num]
                q["answer_status"] = "ok"
        q["flags"] = sorted(set(flags))
        questions.append(q)

    # ---- sanity / status ----
    status = "done"
    nq = len(questions)
    if nq == 0:
        status = "failed"
        notes.append("no questions detected")
    else:
        if is_mcq_paper:
            if nq != 40:
                notes.append(f"expected 40 MCQs, found {nq}")
                status = "partial"
        nums = [q["num"] for q in questions]
        gaps = []
        for x, y in zip(nums, nums[1:]):
            a, b = _num_key(x), _num_key(y)
            if (a[0] == b[0] and b[1] != a[1] + 1) or (a[0] != b[0] and b[1] != 1):
                gaps.append(f"{x}->{y}")
        if gaps:
            notes.append("numbering gaps: " + ", ".join(gaps))
            status = "partial"
        if exam.get("ms_pdf"):
            miss = [q["num"] for q in questions if q["answer_status"] == "missing"]
            if miss:
                notes.append("no markscheme for q" + ",".join(miss))
                if len(miss) > max(1, nq // 10):
                    status = "partial"
        else:
            notes.append("no markscheme pdf")
        if not is_mcq_paper:
            tot = cover_total(qpages)
            if tot is None and mpages:
                # 2010-2011 covers do not print the total; the markscheme front matter does
                for P in mpages[:4]:
                    for L in P.lines:
                        m = re.search(r'Maximum total\s*=\s*\[(\d{2,3})\s*marks\]', L.text)
                        if m:
                            tot = int(m.group(1)); break
                    if tot:
                        break
            msum = sum(q["marks"] or 0 for q in questions)
            if tot:
                if exam["paper"] == "2" and any(q["section"] == "B" for q in questions):
                    a_sum = sum(q["marks"] or 0 for q in questions if q["section"] == "A")
                    b = [q["marks"] or 0 for q in questions if q["section"] == "B"]
                    exp = a_sum + 2 * (max(b) if b else 0)
                    if exp != tot:
                        notes.append(f"marks check: section A {a_sum} + 2x{max(b) if b else 0} != cover total {tot}")
                        status = "partial"
                elif exam["paper"] == "3":
                    pass  # options are alternatives; checked per option below
                elif msum != tot:
                    notes.append(f"marks check: sum {msum} != cover total {tot}")
                    status = "partial"
                if exam["paper"] == "3":
                    base = sum(q["marks"] or 0 for q in questions if q["section"] is None)
                    by_opt = {}
                    for q in questions:
                        if q["section"]:
                            by_opt[q["section"]] = by_opt.get(q["section"], 0) + (q["marks"] or 0)
                    if exam["year"] <= 2015:
                        # 2009 syllabus HL: two options
                        vals = sorted(by_opt.values())
                        ok = vals and all(abs(v - tot / 2) <= 0 for v in vals)
                    else:
                        ok = by_opt and all(base + v == tot for v in by_opt.values())
                    if not ok:
                        notes.append(f"marks check P3: base {base}, options {by_opt}, cover total {tot}")
                        status = "partial"
    if any_ocr_qp:
        notes.append("question paper OCR'd")

    result.update({
        "questions": questions,
        "qp_pages": qdoc.page_count,
        "status": status,
        "notes": "; ".join(x for x in [exam.get("notes") or "", ("segmenter: " + "; ".join(notes)) if notes else ""] if x),
    })
    return result
