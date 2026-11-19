#!/usr/bin/env python3
"""Economics question segmenter (see db/SCHEMA.md, "Segmenter contract").

    segment(exam, out_dir, overrides) -> exam.json dict

Paper structures handled (all IB Economics SL, 2010-2025):
  econ-legacy P1   4 essay questions, Section A (micro, Q1-2) / Section B (macro, Q3-4); (a)[10] + (b)[15]
                   2010-2012 papers have no section headings.
  econ-legacy P2   data response: 2010-2012 five questions (no sections); 2013-2021 four questions,
                   Section A (Q1-2) / Section B (Q3-4); each extract + parts (a)(i)(ii)(b)(c)(d) = [20]
  econ-2020 P1     3 essay questions, (a)[10] + (b)[15]
  econ-2020 P2     2 data-response questions (Texts A-F, tables/charts, parts (a)-(g)) = [40]

Algorithm
  * Text lines (PyMuPDF; tesseract OCR fallback for text-less pages, cached under
    .scratch/seg_economics/ocr) are classified as running junk (page numbers, paper codes,
    "Turn over", "(Question N continued)", "(This question continues ...)", "Blank page", barcodes).
    Paper codes must start 22/88 and barcodes be one unbroken 8-digit run, so axis labels like
    "2012 2013" or year ranges in charts are kept. Symbol/Wingdings private-use glyphs are mapped
    to real characters (circled paragraph numbers ❶-❿, bullets, + − = ×).
  * The page bands above TOP_CUT / below BOT_CUT are whitened as running header/footer, except
    that a real line, table or figure crossing the cut moves it past that content (Pdf.bands): a
    markscheme's last row printed low on a full page is no longer clipped in half.
  * Top-level question numbers are bold "N." lines at the left margin, accepted in strict sequence
    1, 2, 3, ... and only before the "References:"/"Disclaimer:" block at the end of the paper.
  * A question runs from its number line to the next question's number line, or to an
    intervening "Section B" style heading. Every page of the range is rendered at 150 dpi in
    grayscale with the junk whitened, trimmed to its inked rows, long blank runs are shrunk, and
    the pieces are stitched vertically into one WebP.
  * The markscheme is split the same way (front matter before "1." is skipped). The last
    question's markscheme runs to the end of the PDF. Images taller than 16000 px are scaled down.

Overrides (db/SCHEMA.md): questions[{num, qp:[[page,y0,y1],...], ms:[...]}] replace the automatic
regions (page = 0-based PDF page, y in PDF points from page top; headers/footers are still trimmed);
a num unknown to the detector is added as a new question. "drop" removes false-positive question
numbers *before* boundaries are computed (so the preceding question absorbs the dropped region).
"ms_offsets": {"skip_pages": N} ignores markscheme pages < N when looking for question numbers.
"mcq_answers" is honoured although economics has no MCQ. Non-schema extras accepted per question:
"marks" (int), "section" ("A"/"B"/null).

Flags: "diagram-heavy" (raster image or >=6-path vector figure/table in the question), "content-removed"
(IB's public copy says "... removed for copyright reasons"), "parts-removed" (no part marks left in
the paper at all; marks then come from the paper structure), "crop-uncertain" (marks differ from the
paper structure, or the markscheme start was not the first plausible "N."), "text-ocr".
"""

from __future__ import annotations

import hashlib
import math
import re
import subprocess
import tempfile
from pathlib import Path

import fitz  # PyMuPDF
import numpy as np
from PIL import Image

fitz.TOOLS.mupdf_display_errors(False)

ROOT = Path(__file__).resolve().parent.parent
OCR_CACHE = ROOT / ".scratch" / "seg_economics" / "ocr"

DPI = 150
SCALE = DPI / 72.0
MAX_H = 16000          # px; taller stitched images are scaled down (WebP hard limit is 16383)
WEBP_QUALITY = 80
WHITE_LIM = 240        # pixel < this counts as ink
GAP_MAX = 70           # px; blank runs longer than this inside a crop ...
GAP_KEEP = 34          # ... are shrunk to this
PAGE_SEP = 16          # px of white between stitched page pieces
PAD = 8                # px of white added above/below each piece
TOP_CUT = 0.066        # fraction of page height that is running header (unless real content crosses it)
BOT_CUT = 0.956        # fraction of page height below which is running footer (ditto, see Pdf.bands)

# running header/footer lines (matched against the text with all whitespace removed)
JUNK_RES = [re.compile(p) for p in (
    r"^[–—-]\d{1,3}[–—-]$",                    # – 3 –
    r"^[MN]\d{2}/\d/ECON",                     # M15/3/ECONO/SP1/ENG/TZ1/XX(/M)
    r"^Turnover$",
    r"^(22|88)\d{2}[–—-]\d{4}M?$",             # 2215 – 5111 (M = markscheme); 22 = May, 88 = Nov.
                                               # (not "2010–2015" year ranges in figures/tables)
    r"^\(Question\d+continued\)$",
    r"^\(Thisquestioncontinues",
    r"^Blankpage$",
    r"^Pleasedonotwriteonthispage\.?$",
    r"^\d{1,2}pages?$",
    r"^©InternationalBaccalaureateOrgani[sz]ation\d{4}\.?$",
)]
QNUM_RE = re.compile(r"^(\d{1,2})\s*\.$")
MARK_RE = re.compile(r"^\[(\d{1,2})(?:\s*marks?)?\]$")
SECTION_RE = re.compile(r"^Section\s+([A-D])$", re.I)
STOPPER_RES = [re.compile(p, re.I) for p in (
    r"^Section\s+[A-D]$",
    r"^Answer\s+(one|two|three|any)\b.*question",
    r"^(Micro|Macro)economics$",
    r"^(International|Development)\s+economics$",
)]
REMOVED_RE = re.compile(r"[^\n]*(removed for copyright|copyright reasons)[^\n]*", re.I)
BLANK_RE = re.compile(r"^(Blankpage|Pleasedonotwriteonthispage\.?)$", re.I)
REFS_RE = re.compile(r"^(References|Acknowledge?ments?|Disclaimer|Sources?)\s*:?$", re.I)
WORD_RE = re.compile(r"[a-z]{3,}")


# ----------------------------------------------------------------------------------------------
# PDF access helpers
# ----------------------------------------------------------------------------------------------

class Line:
    __slots__ = ("x0", "y0", "x1", "y1", "text", "bold", "junk", "ocr", "spans")

    def __init__(self, x0, y0, x1, y1, text, bold, ocr=False, spans=None):
        self.x0, self.y0, self.x1, self.y1 = x0, y0, x1, y1
        self.text = text
        self.bold = bold
        self.ocr = ocr
        self.junk = is_junk(text)
        self.spans = spans or [(x0, text)]   # [(x0, span text)]

    @property
    def yc(self):
        return (self.y0 + self.y1) / 2


def norm(t: str) -> str:
    return " ".join(re.sub(r"[\x00-\x1f\x7f]", " ", t).split())


# Symbol/Wingdings glyphs come out of the text layer as private-use code points U+F0xx (font code
# + 0xF000). Map the ones these papers use to real characters, per font: the circled paragraph
# numbers of the data-response texts ("(paragraph ❸)") and markscheme bullets/operators.
_SYMBOL_PUA = {0x20: " ", 0x2B: "+", 0x2D: "−", 0x3C: "<", 0x3D: "=", 0x3E: ">", 0xA3: "≤",
               0xA5: "∞", 0xAC: "←", 0xAE: "→", 0xB0: "°", 0xB1: "±", 0xB3: "≥", 0xB4: "×",
               0xB7: "•", 0xB8: "÷", 0xB9: "≠", 0xBB: "≈"}
PUA_MAPS = {
    "symbol": {0xF000 + k: v for k, v in _SYMBOL_PUA.items()},
    # Wingdings: 0x8C-0x95 = ❶-❿ (dingbat negative circled digits), 0x9F = bullet
    "wingdings": {**{0xF08C + i: chr(0x2776 + i) for i in range(10)}, 0xF09F: "•"},
    # Wingdings 2: 0x75-0x7E = ❶-❿
    "wingdings2": {0xF075 + i: chr(0x2776 + i) for i in range(10)},
}


def span_text(s: dict) -> str:
    t = s["text"]
    if not any(0xF000 <= ord(c) <= 0xF0FF for c in t):
        return t
    font = s.get("font", "").lower().replace(" ", "")
    if "wingdings2" in font:
        m = PUA_MAPS["wingdings2"]
    elif "wingdings" in font:
        m = PUA_MAPS["wingdings"]
    else:   # Symbol, or a text font whose Symbol bullet (U+F0B7) lost its font name
        m = PUA_MAPS["symbol"]
    return t.translate(m)


def is_junk(text: str) -> bool:
    s = "".join(text.split())
    if re.fullmatch(r"\d{8}", text.strip()):   # barcode digits (one run; "2012 2013" axis labels are not)
        return True
    return any(r.search(s) for r in JUNK_RES)


class Pdf:
    def __init__(self, path: str):
        self.path = path
        self.doc = fitz.open(path)
        self.n = len(self.doc)
        self._lines: dict[int, list[Line]] = {}
        self._img: dict[int, np.ndarray] = {}
        self._figs: dict[int, list[tuple]] = {}
        self._bands: dict[int, tuple[float, float]] = {}
        self.ocr_pages: set[int] = set()

    def size(self, pn):
        r = self.doc[pn].rect
        return r.width, r.height

    # -- text ---------------------------------------------------------------------------------
    def lines(self, pn: int) -> list[Line]:
        if pn in self._lines:
            return self._lines[pn]
        page = self.doc[pn]
        out = []
        nchars = 0
        for b in page.get_text("dict")["blocks"]:
            if b["type"] != 0:
                continue
            for l in b["lines"]:
                spans = [s for s in l["spans"] if s["text"].strip()]
                if not spans:
                    continue
                text = norm("".join(span_text(s) for s in l["spans"]))
                nchars += len(text)
                f = spans[0]
                bold = bool(f["flags"] & 16) or "bold" in f["font"].lower() or ",b" in f["font"].lower()
                x0, y0, x1, y1 = l["bbox"]
                sp = [(s["bbox"][0], norm(span_text(s))) for s in spans]
                out.append(Line(x0, y0, x1, y1, text, bold, spans=sp))
        if nchars < 15 and self._has_ink(pn):
            ocr = self._ocr_lines(pn)
            if ocr:
                out = ocr
                self.ocr_pages.add(pn)
        out.sort(key=lambda z: (round(z.y0, 0), z.x0))
        self._lines[pn] = out
        return out

    def is_blank(self, pn: int) -> bool:
        """'Blank page' / 'Please do not write on this page' pages (may still carry a frame)."""
        ls = self.lines(pn)
        return (any(BLANK_RE.match("".join(l.text.split())) for l in ls)
                and not any(not l.junk for l in ls))

    def bands(self, pn: int) -> tuple[float, float]:
        """(top, bottom) in pt of the page's content area. Running headers/footers live above
        TOP_CUT / below BOT_CUT, but a real content line, table or figure that crosses one of those
        lines (e.g. a markscheme's last row printed low on a full page) pushes the cut past it,
        together with anything chained to it within 3 pt (a table's bottom rule). Junk lines and
        footer barcodes are whitened separately and never extend the area."""
        if pn in self._bands:
            return self._bands[pn]
        page = self.doc[pn]
        _, ph = self.size(pn)
        top, bot = TOP_CUT * ph, BOT_CUT * ph
        items = [(ln.y0, ln.y1) for ln in self.lines(pn) if not ln.junk and ln.text]
        if pn not in self.ocr_pages:
            try:
                items += [(d["rect"].y0, d["rect"].y1) for d in page.get_drawings()]
            except Exception:
                pass
            items += [(b["bbox"][1], b["bbox"][3]) for b in page.get_text("dict")["blocks"]
                      if b["type"] == 1 and b["bbox"][1] <= 0.93 * ph]
        # page frames / full-height rules say nothing about where the content stops
        items = [(a, b) for a, b in items if b - a < 0.6 * ph]
        lo_lim, hi_lim = 0.02 * ph, 0.985 * ph
        changed = True
        while changed:
            changed = False
            for a, b in items:
                # crosses the cut (by > 0.5 pt), or once moved, starts within 3 pt of it
                slack = 3.0 if bot > BOT_CUT * ph else -0.5
                if a < bot + slack and b > bot and b + 1.0 <= hi_lim:
                    bot, changed = b + 1.0, True
                slack = 3.0 if top < TOP_CUT * ph else -0.5
                if b > top - slack and a < top and a - 1.0 >= lo_lim:
                    top, changed = a - 1.0, True
        self._bands[pn] = (top, bot)
        return top, bot

    def _has_ink(self, pn) -> bool:
        a = self.clean(pn, lines_ready=False)
        return bool(((a < WHITE_LIM).sum(1) >= 3).sum() > 40)

    def _ocr_lines(self, pn) -> list[Line]:
        """tesseract fallback: returns Line objects in PDF points (bold unknown -> True)."""
        OCR_CACHE.mkdir(parents=True, exist_ok=True)
        key = hashlib.sha1(f"{self.path}|{pn}".encode()).hexdigest()[:20]
        tsv_path = OCR_CACHE / f"{key}.tsv"
        ocr_dpi = 300
        if not tsv_path.exists():
            pix = self.doc[pn].get_pixmap(matrix=fitz.Matrix(ocr_dpi / 72, ocr_dpi / 72),
                                          colorspace=fitz.csGRAY, alpha=False)
            with tempfile.TemporaryDirectory() as td:
                png = Path(td) / "p.png"
                pix.save(str(png))
                try:
                    r = subprocess.run(["tesseract", str(png), "stdout", "--psm", "4", "tsv"],
                                       capture_output=True, text=True, timeout=120)
                    tsv = r.stdout
                except Exception:
                    tsv = ""
            tsv_path.write_text(tsv)
        tsv = tsv_path.read_text()
        groups: dict[tuple, list] = {}
        for row in tsv.splitlines()[1:]:
            c = row.split("\t")
            if len(c) < 12 or not c[11].strip():
                continue
            try:
                conf = float(c[10])
            except ValueError:
                continue
            if conf < 0:
                continue
            k = (int(c[2]), int(c[3]), int(c[4]))
            groups.setdefault(k, []).append((int(c[6]), int(c[7]), int(c[8]), int(c[9]), c[11]))
        s = 72.0 / ocr_dpi
        out = []
        for words in groups.values():
            words.sort()
            x0 = min(w[0] for w in words) * s
            y0 = min(w[1] for w in words) * s
            x1 = max(w[0] + w[2] for w in words) * s
            y1 = max(w[1] + w[3] for w in words) * s
            sp = [(w[0] * s, norm(w[4])) for w in words]
            out.append(Line(x0, y0, x1, y1, norm(" ".join(w[4] for w in words)), True, ocr=True, spans=sp))
        return out

    # -- rendering ----------------------------------------------------------------------------
    def clean(self, pn: int, lines_ready: bool = True) -> np.ndarray:
        """150-dpi grayscale render with running headers/footers whitened."""
        if pn in self._img and lines_ready:
            return self._img[pn]
        page = self.doc[pn]
        pix = page.get_pixmap(matrix=fitz.Matrix(SCALE, SCALE), colorspace=fitz.csGRAY, alpha=False)
        a = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.stride)[:, :pix.w].copy()
        H = a.shape[0]
        _, ph = self.size(pn)
        r_top, r_bot = int(TOP_CUT * H), int(BOT_CUT * H)
        if lines_ready:   # (not while the text layer is still being read for the OCR decision)
            top, bot = self.bands(pn)
            if top < TOP_CUT * ph:
                r_top = int(top * SCALE)
            if bot > BOT_CUT * ph:
                r_bot = int(math.ceil(bot * SCALE))
        a[:r_top] = 255
        a[r_bot:] = 255
        # barcodes / logos near the bottom edge
        for b in page.get_text("dict")["blocks"]:
            if b["type"] == 1 and b["bbox"][1] > 0.93 * ph:
                self._white(a, b["bbox"], 2)
        if not lines_ready:
            return a
        for ln in self.lines(pn):
            if ln.junk:
                self._white(a, (ln.x0, ln.y0, ln.x1, ln.y1), 1.5)
        self._img[pn] = a
        return a

    @staticmethod
    def _white(a, bbox, pad):
        x0, y0, x1, y1 = bbox
        r0 = max(0, int((y0 - pad) * SCALE))
        r1 = min(a.shape[0], int(math.ceil((y1 + pad) * SCALE)))
        c0 = max(0, int((x0 - pad) * SCALE))
        c1 = min(a.shape[1], int(math.ceil((x1 + pad) * SCALE)))
        a[r0:r1, c0:c1] = 255

    def figures(self, pn) -> list[tuple]:
        """bboxes (pt) of raster images and large vector drawings (charts, tables)."""
        if pn in self._figs:
            return self._figs[pn]
        page = self.doc[pn]
        _, ph = self.size(pn)
        figs = []
        for b in page.get_text("dict")["blocks"]:
            if b["type"] == 1:
                x0, y0, x1, y1 = b["bbox"]
                if (y1 - y0) > 60 and (x1 - x0) > 80 and y0 > TOP_CUT * ph and y1 < BOT_CUT * ph:
                    figs.append((x0, y0, x1, y1))
        try:
            rects = [d["rect"] for d in page.get_drawings()]
        except Exception:
            rects = []
        # cluster drawing rects into figure-sized groups
        boxes: list[list[float]] = []   # [x0, y0, x1, y1, n_items]
        for r in rects:
            if r.height < 1 and r.width < 1:
                continue
            if r.y0 < TOP_CUT * ph or r.y1 > BOT_CUT * ph:
                continue
            placed = False
            for bx in boxes:
                if r.x0 <= bx[2] + 4 and r.x1 >= bx[0] - 4 and r.y0 <= bx[3] + 4 and r.y1 >= bx[1] - 4:
                    bx[0] = min(bx[0], r.x0); bx[1] = min(bx[1], r.y0)
                    bx[2] = max(bx[2], r.x1); bx[3] = max(bx[3], r.y1)
                    bx[4] += 1
                    placed = True
                    break
            if not placed:
                boxes.append([r.x0, r.y0, r.x1, r.y1, 1])
        for bx in boxes:
            # a lone frame around an extract is not a figure; charts/tables have many paths
            if bx[3] - bx[1] > 80 and bx[2] - bx[0] > 120 and bx[4] >= 6:
                figs.append(tuple(bx[:4]))
        self._figs[pn] = figs
        return figs


# ----------------------------------------------------------------------------------------------
# Region handling: a region is a list of (page, y0_pt, y1_pt)
# ----------------------------------------------------------------------------------------------

def region_from_bounds(pdf: Pdf, start: tuple[int, float], end: tuple[int, float]) -> list[list]:
    """pages start[0]..end[0]; end is exclusive (page, y)."""
    sp, sy = start
    ep, ey = end
    out = []
    for pn in range(sp, min(ep, pdf.n - 1) + 1):
        _, ph = pdf.size(pn)
        y0 = sy if pn == sp else 0.0
        y1 = ey if pn == ep else ph
        if y1 - y0 > 2:
            out.append([pn, y0, y1])
    return out


def piece(pdf: Pdf, pn: int, y0: float, y1: float):
    """Crop the inked rows of page pn within [y0, y1] pt -> (array, (cmin, cmax)) or None."""
    if pn < 0 or pn >= pdf.n or pdf.is_blank(pn):
        return None
    a = pdf.clean(pn)
    H = a.shape[0]
    r0 = max(0, int(y0 * SCALE))
    r1 = min(H, int(math.ceil(y1 * SCALE)))
    if r1 - r0 < 3:
        return None
    sub = a[r0:r1]
    dark = sub < WHITE_LIM
    rows = dark.sum(1) >= 2
    if rows.sum() < 3:
        return None
    # drop isolated thin rules (separator lines above footnotes / end-of-paper lines) at the
    # top or bottom edge of the piece
    runs = []
    i, n = 0, len(rows)
    while i < n:
        if rows[i]:
            j = i
            while j < n and rows[j]:
                j += 1
            runs.append([i, j])
            i = j
        else:
            i += 1
    while runs and runs[-1][1] - runs[-1][0] <= 4 and (len(runs) == 1 or runs[-1][0] - runs[-2][1] > 25):
        rows[runs[-1][0]: runs[-1][1]] = False
        runs.pop()
    while runs and runs[0][1] - runs[0][0] <= 4 and (len(runs) == 1 or runs[1][0] - runs[0][1] > 25):
        rows[runs[0][0]: runs[0][1]] = False
        runs.pop(0)
    if rows.sum() < 3:
        return None
    idx = np.nonzero(rows)[0]
    sub = sub[idx[0]: idx[-1] + 1]
    rows = rows[idx[0]: idx[-1] + 1]
    cols = np.nonzero((sub < WHITE_LIM).sum(0) >= 1)[0]
    # shrink long blank runs (never touches inked rows)
    keep = np.ones(len(rows), dtype=bool)
    i = 0
    n = len(rows)
    while i < n:
        if rows[i]:
            i += 1
            continue
        j = i
        while j < n and not rows[j]:
            j += 1
        if j - i > GAP_MAX:
            keep[i + GAP_KEEP // 2: j - GAP_KEEP // 2] = False
        i = j
    sub = sub[keep]
    return sub, (int(cols[0]), int(cols[-1]))


def render_region(pdf: Pdf, region: list, out_path: Path) -> dict | None:
    pieces = []
    for pn, y0, y1 in region:
        p = piece(pdf, int(pn), float(y0), float(y1))
        if p is not None:
            pieces.append(p)
    if not pieces:
        return None
    width = max(p[0].shape[1] for p in pieces)
    c0 = max(0, min(p[1][0] for p in pieces) - 14)
    c1 = min(width, max(p[1][1] for p in pieces) + 15)
    parts = []
    for k, (arr, _) in enumerate(pieces):
        if arr.shape[1] < width:  # mixed page sizes
            arr = np.pad(arr, ((0, 0), (0, width - arr.shape[1])), constant_values=255)
        arr = arr[:, c0:c1]
        pad = np.full((PAD, arr.shape[1]), 255, np.uint8)
        parts += [pad, arr, pad]
        if k < len(pieces) - 1:
            parts.append(np.full((PAGE_SEP, arr.shape[1]), 255, np.uint8))
    img = np.vstack(parts)
    dpi = DPI
    im = Image.fromarray(img, "L")
    if img.shape[0] > MAX_H:
        s = MAX_H / img.shape[0]
        dpi = round(DPI * s)
        im = im.resize((max(1, round(im.width * s)), MAX_H), Image.LANCZOS)
    im.save(out_path, "WEBP", quality=WEBP_QUALITY, method=4)
    return {"h": im.height, "w": im.width, "dpi": dpi, "pieces": len(pieces)}


def region_lines(pdf: Pdf, region: list) -> list[tuple[int, Line]]:
    out = []
    for pn, y0, y1 in region:
        pn = int(pn)
        if pn < 0 or pn >= pdf.n:
            continue
        top, bot = pdf.bands(pn)
        for ln in pdf.lines(pn):
            if ln.junk or not (y0 - 1 <= ln.yc <= y1 + 1):
                continue
            if ln.y1 < top or ln.y0 > bot:
                continue
            out.append((pn, ln))
    return out


def region_text(pdf: Pdf, region: list) -> str:
    """reading-order text: lines grouped into rows by vertical centre, rows left-to-right."""
    out: list[str] = []
    by_page: dict[int, list[Line]] = {}
    order: list[int] = []
    for pn, ln in region_lines(pdf, region):
        if pn not in by_page:
            by_page[pn] = []
            order.append(pn)
        by_page[pn].append(ln)
    for pn in order:
        rows: list[list[Line]] = []
        for ln in sorted(by_page[pn], key=lambda z: (z.yc, z.x0)):
            if rows and abs(ln.yc - sum(z.yc for z in rows[-1]) / len(rows[-1])) < 3.5:
                rows[-1].append(ln)
            else:
                rows.append([ln])
        out += ["  ".join(z.text for z in sorted(r, key=lambda z: z.x0)) for r in rows]
    return "\n".join(out).strip()


def region_marks(pdf: Pdf, region: list) -> int | None:
    tot = 0
    found = False
    for pn, ln in region_lines(pdf, region):
        w, _ = pdf.size(pn)
        m = MARK_RE.match(ln.text)
        if m and ln.x0 > 0.62 * w:
            tot += int(m.group(1))
            found = True
            continue
        # mark glued to the end of a text line: "... (Text D, paragraph 2).[2]"
        m = re.search(r"\[(\d{1,2})(?:\s*marks?)?\]$", ln.text)
        if m and ln.x1 > 0.88 * w:
            tot += int(m.group(1))
            found = True
    return tot if found else None


def region_has_figure(pdf: Pdf, region: list) -> bool:
    for pn, y0, y1 in region:
        for f in pdf.figures(int(pn)):
            if f[1] >= y0 - 2 and f[3] <= y1 + 2:
                return True
    return False


def region_ocr(pdf: Pdf, region: list) -> bool:
    return any(int(pn) in pdf.ocr_pages for pn, _, _ in region)


# ----------------------------------------------------------------------------------------------
# Question-number detection
# ----------------------------------------------------------------------------------------------

def left_margin(pdf: Pdf, first_page: int = 1) -> float:
    xs = []
    for pn in range(min(first_page, pdf.n - 1), pdf.n):
        xs += [ln.x0 for ln in pdf.lines(pn) if not ln.junk and ln.x0 > 15]
    if not xs:
        return 42.5
    xs.sort()
    return xs[min(len(xs) - 1, max(0, len(xs) // 200))]


def follower(lines: list[Line], i: int) -> str:
    ln = lines[i]
    same = [z for z in lines if z is not ln and abs(z.y0 - ln.y0) < 6 and z.x0 > ln.x1 - 1]
    if same:
        same.sort(key=lambda z: z.x0)
        return " ".join(z.text for z in same)
    for z in lines[i + 1:]:
        if not z.junk:
            return z.text
    return ""


def candidates(pdf: Pdf, pages, margin: float) -> list[dict]:
    out = []
    for pn in pages:
        lines = pdf.lines(pn)
        w, _ = pdf.size(pn)
        xlim = min(margin + 22, 0.15 * w)
        for i, ln in enumerate(lines):
            if ln.junk or ln.x0 > xlim:
                continue
            m = QNUM_RE.match(ln.text)
            fol = None
            if not m and ln.ocr and len(ln.spans) > 1:
                # OCR lines are whole text rows: "1. (a) Explain ..." -> number + follower
                m = QNUM_RE.match(ln.spans[0][1])
                fol = " ".join(t for _, t in ln.spans[1:])
            if not m:
                continue
            if fol is None:
                fol = follower(lines, i)
            starts_part = bool(re.match(r"^\((a|i)\)", fol)) or bool(re.match(r"^\[\d", fol))
            out.append({"num": int(m.group(1)), "pn": pn, "y": ln.y0, "bold": ln.bold,
                        "follow": fol, "part": starts_part})
    out.sort(key=lambda c: (c["pn"], c["y"]))
    return out


def find_stop(pdf: Pdf, after: tuple[int, float]):
    """first References/Disclaimer heading after `after` -> (pn, y) or None."""
    for pn in range(after[0], pdf.n):
        for ln in pdf.lines(pn):
            if (pn, ln.y0) <= after or ln.junk:
                continue
            if REFS_RE.match(ln.text) and ln.bold:
                return (pn, ln.y0)
    return None


def stopper_between(pdf: Pdf, start: tuple[int, float], end: tuple[int, float]):
    """earliest section-heading style line strictly inside (start, end)."""
    for pn in range(start[0], min(end[0], pdf.n - 1) + 1):
        for ln in pdf.lines(pn):
            pos = (pn, ln.y0)
            if pos <= (start[0], start[1] + 5) or pos >= end or ln.junk:
                continue
            if any(r.match(ln.text) for r in STOPPER_RES):
                return (pn, ln.y0 - 3)
    return None


def doc_end(pdf: Pdf) -> tuple[int, float]:
    pn = pdf.n - 1
    return (pn, pdf.size(pn)[1])


def tokens(t: str) -> set[str]:
    return set(WORD_RE.findall(t.lower()))


# ----------------------------------------------------------------------------------------------
# Paper structure expectations
# ----------------------------------------------------------------------------------------------

def expected_structure(exam: dict) -> dict:
    legacy = exam.get("syllabus") == "econ-legacy"
    paper = str(exam.get("paper"))
    if paper == "1":
        return {"count": 4 if legacy else 3, "marks": 25, "qtype": "essay"}
    if paper == "2":
        if legacy:
            return {"count": 5 if exam.get("year", 0) <= 2012 else 4, "marks": 20, "qtype": "data"}
        return {"count": 2, "marks": 40, "qtype": "data"}
    return {"count": None, "marks": None, "qtype": "long"}


def cover_info(pdf: Pdf) -> dict:
    txt = " ".join(ln.text for pn in range(min(2, pdf.n)) for ln in pdf.lines(pn))
    info = {}
    m = re.search(r"maximum mark for this examination paper is\s*\[(\d+)\s*marks?\]", txt, re.I)
    if m:
        info["total"] = int(m.group(1))
    words = {"one": 1, "two": 2, "three": 3, "four": 4}
    secs = re.findall(r"Section\s+[A-D]\s*:\s*answer\s+(one|two|three)\s+question", txt, re.I)
    if secs:
        info["answer"] = sum(words[s.lower()] for s in secs)
    else:
        m = re.search(r"Answer\s+(one|two|three|four)\s+questions?", txt, re.I)
        if m:
            info["answer"] = words[m.group(1).lower()]
    return info


# ----------------------------------------------------------------------------------------------
# Main entry point
# ----------------------------------------------------------------------------------------------

def _num_key(n: str):
    m = re.match(r"(\d+)", str(n))
    return (int(m.group(1)) if m else 999, str(n))


def _clean_override_region(reg) -> list:
    out = []
    for r in reg or []:
        if isinstance(r, (list, tuple)) and len(r) >= 3:
            out.append([int(r[0]), float(r[1]), float(r[2])])
    return out


def segment(exam: dict, out_dir: Path, overrides: dict | None) -> dict:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    ov = overrides or {}
    ov_q = {str(q.get("num")): q for q in ov.get("questions", []) if q.get("num") is not None}
    drop = {str(d) for d in ov.get("drop", [])}
    skip_ms = int((ov.get("ms_offsets") or {}).get("skip_pages", 0) or 0)
    mcq_ov = {str(k): v for k, v in (ov.get("mcq_answers") or {}).items()}

    exp = expected_structure(exam)
    notes: list[str] = []
    result = dict(exam)
    result.update({"questions": [], "qp_pages": 0, "status": "failed"})

    qp = Pdf(exam["qp_pdf"])
    result["qp_pages"] = qp.n
    cover = cover_info(qp)

    # ---------------- question paper ------------------------------------------------------
    margin = left_margin(qp)
    cands = [c for c in candidates(qp, range(1, qp.n), margin)
             if c["bold"] or c["part"] or re.match(r"^(Study|Read)\b", c["follow"])]
    first = next((c for c in cands if c["num"] == 1), None)
    stop = find_stop(qp, (first["pn"], first["y"])) if first else None

    def pick_sequence(cs, stop_at):
        seq, k = [], 1
        for c in cs:
            if stop_at and (c["pn"], c["y"]) >= stop_at:
                break
            if c["num"] == k:
                seq.append(c)
                k += 1
        return seq

    seq = pick_sequence(cands, stop)
    if exp["count"] and len(seq) < exp["count"] and stop:
        alt = pick_sequence(cands, None)
        if len(alt) == exp["count"]:
            seq, stop = alt, None
            notes.append("ignored references stop marker")
    seq = [c for c in seq if str(c["num"]) not in drop]

    # section headings
    sections = []
    for pn in range(1, qp.n):
        for ln in qp.lines(pn):
            m = SECTION_RE.match(ln.text)
            if m and not ln.junk:
                sections.append(((pn, ln.y0), m.group(1).upper()))

    end_of_paper = stop if stop else doc_end(qp)
    auto_qp: dict[str, dict] = {}
    for i, c in enumerate(seq):
        start = (c["pn"], max(0.0, c["y"] - 3))
        end = (seq[i + 1]["pn"], seq[i + 1]["y"] - 3) if i + 1 < len(seq) else end_of_paper
        st = stopper_between(qp, start, end)
        if st:
            end = st
        sec = None
        for pos, s in sections:
            if pos < (c["pn"], c["y"]):
                sec = s
        auto_qp[str(c["num"])] = {"region": region_from_bounds(qp, start, end), "section": sec}

    nums = sorted(set(auto_qp) | {n for n, q in ov_q.items() if q.get("qp")}, key=_num_key)
    nums = [n for n in nums if n not in drop]

    # ---------------- markscheme ----------------------------------------------------------
    ms = Pdf(exam["ms_pdf"]) if exam.get("ms_pdf") else None
    auto_ms: dict[str, list] = {}
    ms_uncertain: set[str] = set()
    if ms is not None:
        mmargin = left_margin(ms, max(1, skip_ms))
        mc = candidates(ms, range(max(1, skip_ms), ms.n), mmargin)
        mc = [c for c in mc if c["bold"] or c["part"]]
        picks = []
        pos = (-1, -1.0)
        for n in nums:
            qtext = ""
            if n in auto_qp:
                qtext = region_text(qp, auto_qp[n]["region"])
            elif n in ov_q:
                qtext = region_text(qp, _clean_override_region(ov_q[n].get("qp")))
            # the markscheme restates the question parts: compare with text after "(a)"
            k = qtext.find("(a)")
            qtok = tokens(qtext[k if k >= 0 else 0:][:1500])
            opts = [c for c in mc if c["num"] == int(_num_key(n)[0]) and (c["pn"], c["y"]) > pos]
            if not opts:
                continue
            best, best_score = None, -1.0
            for c in opts[:6]:
                nxt = ms_text_after(ms, c, 500)
                ov_ = len(qtok & tokens(nxt)) / (len(qtok) + 1) if qtok else 0
                score = (1.0 if c["part"] else 0) + ov_ + (0.2 if c["bold"] else 0)
                if score > best_score + 0.15:
                    best, best_score = c, score
            if best is not opts[0]:
                ms_uncertain.add(n)
            picks.append((n, best))
            pos = (best["pn"], best["y"])
        for i, (n, c) in enumerate(picks):
            start = (c["pn"], max(0.0, c["y"] - 3))
            end = (picks[i + 1][1]["pn"], picks[i + 1][1]["y"] - 3) if i + 1 < len(picks) else doc_end(ms)
            st = stopper_between(ms, start, end)
            if st:
                end = st
            auto_ms[n] = region_from_bounds(ms, start, end)
    else:
        notes.append("no markscheme PDF")

    # ---------------- build questions ------------------------------------------------------
    questions = []
    for n in nums:
        o = ov_q.get(n, {})
        flags: list[str] = []
        if o.get("qp"):
            qreg = _clean_override_region(o["qp"])
        elif n in auto_qp:
            qreg = auto_qp[n]["region"]
        else:
            continue
        sec = o.get("section", auto_qp.get(n, {}).get("section"))
        if o.get("ms") and ms is not None:
            mreg = _clean_override_region(o["ms"])
        else:
            mreg = auto_ms.get(n)
            if n in ms_uncertain and not o.get("ms"):
                flags.append("crop-uncertain")

        img_name = f"q{n}.webp"
        info = render_region(qp, qreg, out_dir / img_name)
        if info is None:
            notes.append(f"q{n}: empty question region")
            continue
        text = region_text(qp, qreg)
        marks = o.get("marks", region_marks(qp, qreg))
        if region_ocr(qp, qreg):
            flags.append("text-ocr")
        if region_has_figure(qp, qreg):
            flags.append("diagram-heavy")
        removed = REMOVED_RE.search(text)
        if removed:
            # IB's public copy blanks copyrighted extracts/figures (sometimes the whole set of parts)
            flags.append("content-removed")
            notes.append(f"q{n}: '{removed.group(0).strip()}'")
        if exp["marks"] and marks != exp["marks"] and not o.get("qp") and "marks" not in o:
            if marks is None and removed:
                marks = exp["marks"]
                flags.append("parts-removed")
                notes.append(f"q{n}: parts removed from public paper, marks={marks} from paper structure")
            else:
                flags.append("crop-uncertain")
                notes.append(f"q{n}: marks {marks} != expected {exp['marks']}")

        ms_image, ms_text = None, None
        if mreg:
            minfo = render_region(ms, mreg, out_dir / f"q{n}_ms.webp")
            if minfo is not None:
                ms_image = f"q{n}_ms.webp"
                ms_text = region_text(ms, mreg) or None
                if region_ocr(ms, mreg) and "text-ocr" not in flags:
                    flags.append("text-ocr")
                if minfo["dpi"] < DPI:
                    notes.append(f"q{n}: markscheme image downscaled to ~{minfo['dpi']} dpi")
        mcq = mcq_ov.get(n)
        questions.append({
            "id": f"{exam['exam_id']}-q{n}",
            "num": n,
            "section": sec,
            "marks": marks,
            "qtype": exp["qtype"],
            "image": img_name,
            "ms_image": ms_image,
            "text": text,
            "ms_text": ms_text,
            "mcq_answer": mcq,
            "topics": [],
            "subtopics": [],
            "answer_status": "ok" if (ms_image or mcq) else "missing",
            "flags": sorted(set(flags), key=flags.index),
        })

    # ---------------- sanity checks / status ------------------------------------------------
    result["questions"] = questions
    nq = len(questions)
    if exp["count"] and nq != exp["count"]:
        notes.append(f"found {nq} questions, expected {exp['count']}")
    if cover.get("total") and cover.get("answer") and questions:
        qm = [q["marks"] for q in questions if q["marks"]]
        if qm and cover["total"] != cover["answer"] * max(set(qm), key=qm.count):
            notes.append(f"cover total [{cover['total']} marks] != {cover['answer']} x {max(set(qm), key=qm.count)}")
    missing = [q["num"] for q in questions if q["answer_status"] != "ok"]
    if missing and ms is not None:
        notes.append("no markscheme crop for q" + ",".join(missing))
    if not questions:
        result["status"] = "failed"
    elif (exp["count"] and nq != exp["count"]) or missing:
        result["status"] = "partial"
    else:
        result["status"] = "done"
    seg_notes = "; ".join(notes)
    base = exam.get("notes") or ""
    result["notes"] = (base + (" || seg: " + seg_notes if seg_notes else "")).strip()
    return result


def ms_text_after(ms: Pdf, c: dict, nchars: int) -> str:
    buf = []
    total = 0
    for pn in range(c["pn"], min(ms.n, c["pn"] + 2)):
        for ln in ms.lines(pn):
            if pn == c["pn"] and ln.y0 < c["y"] - 1:
                continue
            if ln.junk:
                continue
            buf.append(ln.text)
            total += len(ln.text)
            if total > nchars:
                return " ".join(buf)
    return " ".join(buf)
