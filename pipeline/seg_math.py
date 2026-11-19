#!/usr/bin/env python3
"""Math (Mathematics HL 1995-2020, Math AA HL 2021+) question segmenter.

Contract: see db/SCHEMA.md ("Segmenter contract").  Exposes

    segment(exam: dict, out_dir: pathlib.Path, overrides: dict | None) -> dict

which writes q<num>.webp / q<num>_ms.webp into out_dir and returns the exam.json content.

How it works (question paper and markscheme use the same machinery):
  1. Every page is turned into "lines" (PyMuPDF spans, or tesseract TSV for scanned pages - cached
     under .scratch/seg_math/ocr/), images and vector drawings.  Running headers / footers are found
     by regex + recurrence across pages and define a per-page body box.  Dotted answer lines,
     answer boxes, "do not write on this page" etc. become white-out masks.
  2. Top-level question numbers ("7." at the left text column, usually bold, usually followed by
     "[Maximum mark: N]") are collected as candidates and the best chain 1,2,3,... is chosen by
     dynamic programming (numbering may restart at 1 after a SECTION heading, as in the combined
     2006/07 paper 3 - those questions get nums "A1".."D5").
  3. A question's region runs from its number to the next question (or a SECTION heading); each page
     piece is rendered at 150 dpi grayscale, masked, trimmed to inked rows, long blank runs are
     squeezed, and pieces are stacked into one tall image.
  4. The markscheme is split the same way after skipping its front matter (instructions to
     examiners); headings must carry the period ("3.") or read "QUESTION 3".

Overrides (all optional, see SCHEMA.md): questions[].qp / questions[].ms = [[page, y0, y1], ...]
(0-based page, PDF points from page top), ms_offsets.skip_pages, drop, mcq_answers.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import fitz
import numpy as np
from PIL import Image

fitz.TOOLS.mupdf_display_errors(False)
ROOT = Path(__file__).resolve().parent.parent
OCR_CACHE = ROOT / ".scratch" / "seg_math" / "ocr"
DPI = 150
SCALE = DPI / 72.0
WEBP_QUALITY = 80
OCR_DPI = 300
MAX_IMG_H = 16000

# ----------------------------------------------------------------------------- text helpers

_WS = re.compile(r"[\s      \t]+")


_SYM = dict(zip(range(0x20, 0x7F), " !∀#∃%&∋()∗+,−./0123456789:;<=>?≅ΑΒΧΔΕΦΓΗΙϑΚΛΜΝΟΠΘΡΣΤΥςΩΞΨΖ[∴]⊥_‾"
                                     "αβχδεφγηιϕκλμνοπθρστυϖωξψζ{|}∼"))
_SYM.update({0xA1: "ϒ", 0xA2: "′", 0xA3: "≤", 0xA4: "⁄", 0xA5: "∞", 0xA6: "ƒ", 0xAB: "↔", 0xAC: "←",
             0xAD: "↑", 0xAE: "→", 0xAF: "↓", 0xB0: "°", 0xB1: "±", 0xB2: "″", 0xB3: "≥", 0xB4: "×",
             0xB5: "∝", 0xB6: "∂", 0xB7: "•", 0xB8: "÷", 0xB9: "≠", 0xBA: "≡", 0xBB: "≈", 0xBC: "…",
             0xBD: "|", 0xBE: "—", 0xC0: "ℵ", 0xC4: "⊗", 0xC5: "⊕", 0xC6: "∅", 0xC7: "∩", 0xC8: "∪",
             0xC9: "⊃", 0xCA: "⊇", 0xCB: "⊄", 0xCC: "⊂", 0xCD: "⊆", 0xCE: "∈", 0xCF: "∉", 0xD0: "∠",
             0xD1: "∇", 0xD5: "∏", 0xD6: "√", 0xD7: "⋅", 0xD8: "¬", 0xD9: "∧", 0xDA: "∨", 0xDB: "⇔",
             0xDC: "⇐", 0xDD: "⇑", 0xDE: "⇒", 0xDF: "⇓", 0xE0: "◊", 0xE1: "〈", 0xE5: "∑", 0xF1: "〉",
             0xF2: "∫"})
_PUA = {0xF000 + k: v for k, v in _SYM.items()}
_PUA.update({c: None for c in range(0xF0E6, 0xF100) if c not in _PUA})
_PUA.update({c: None for c in range(0xF8E5, 0xF900)})


def norm(t: str) -> str:
    return _WS.sub(" ", t.translate(_PUA)).strip()


DOT_CHARS = set(".…·_‥   \t")


def is_dots(t: str) -> bool:
    s = t.strip()
    if not s:
        return False
    # dotted answer lines set in a font without a unicode map
    bad = sum(c in "\ufffd\x08" for c in s)
    if len(s) >= 10 and bad >= 0.9 * len(s):
        return True
    return set(s) <= DOT_CHARS and sum(c in ".…_·‥" for c in s) >= 4


HEADER_RES = [re.compile(p, re.I) for p in (
    r"^[-–—‒]\s*\d+\s*[-–—‒]$",                       # – 3 –
    r"^[MN]\d{2}\s*/\s*\d",                          # M15/5/MATHL/..., M03/510/H(1)
    r"^\d{3,4}\s*[-–]\s*\d{3,4}$",                    # 2210-7203, 223-236
    r"^\d{1,3}\s*EP\s*\d{1,3}$",                      # 16EP02
    r"^turn over$",
    r"^\d+\s+pages?$",
    r"©",
    r"international baccalaureate",
    r"baccalaur[ée]at international",
    r"bachillerato internacional",
    r"^ib diploma programme",
    r"^programme du diplôme",
    r"^programa del diploma",
)]
FOOTER_EXTRA_RES = [re.compile(p, re.I) for p in (
    r"^\d{1,4}$",                                    # page/barcode numbers at the bottom
    r"^continued\W*$",
    r"^\(?\s*continued\s+on",
)]
IGNORE_RES = [re.compile(p, re.I) for p in (
    r"^\(?\s*this question continues on the (following|next) page\s*\)?\.?$",
    r"^\(?\s*question\s+\d+\s*(?:\([a-z]+\)\s*)?continued\s*\)?\.?$",
    r"^\(?\s*continued\s*\)?\W*$",
    r"^\(?\s*\.\.\.\s*continued\s*\)?$",
    r"^do not write (solutions )?on this page\.?$",
    r"^please do not write on this page\.?$",
    r"^answers written on this page\.?$",
    r"^will not be marked\.?$",
    r"^answers written on this page will not be marked\.?$",
    r"^turn over$",
    r"^blank page$",
    r"^this page (is )?intentionally left blank\.?$",
    r"^\(?\s*this question continues",
    r"^\(?\s*question\s+[a-d]?\d+\s+continued",
)]
# a line from which the rest of the page is boilerplate
TAIL_RES = [re.compile(p, re.I) for p in (
    r"^references\s*:?$",
    r"^disclaimer\s*:",
    r"^acknowledge?ments?\s*:?$",
    r"^© international baccalaureate organization",
)]
SECTION_RE = re.compile(r"^SECTION\s+([A-E])\s*$", re.I)
ANSWERISH_RE = re.compile(
    r"^(working\s*:?|answers?\s*:?|\(?[a-h]\)|\(?[ivx]{1,4}\)|\(?[a-h]\)\s*\(?[ivx]{1,4}\))$", re.I)
WORKING_RE = re.compile(r"^W[o0]rk(ing|ings|in)?\s*[:;.,]?$", re.I)
MAXMARK_RE = re.compile(r"\[\s*Maximum\s*marks?\s*[:;.]?\s*(\d{1,3})\s*\]", re.I)
PARTMARK_RE = re.compile(r"\[\s*(\d{1,2})\s*(?:marks?)?\s*\]", re.I)
TOTAL_RE = re.compile(r"total\s*[:\-]?\s*\[\s*(\d{1,3})\s*marks?\s*\]", re.I)
MSMARKS_RE = re.compile(r"\[\s*(\d{1,2})\s*marks?\s*\]", re.I)
FM_RES = [re.compile(p, re.I) for p in (
    r"^instructions to examiners", r"^abbreviations$", r"^using the markscheme", r"^method of marking",
    r"^general$", r"^mis-?read", r"^follow[- ]through", r"^discretionary marks", r"^alternative (methods|forms)",
    r"^accuracy of answers", r"^calculators?$", r"^crossed out work", r"^examples?:?$", r"^style$",
    r"^presentation of candidate work", r"^candidate work", r"^implied marks", r"^n marks",
    r"^method and answer", r"^this markscheme is (the property|confidential)", r"^level of accuracy",
    r"^graphic display calculators", r"^marks awarded for", r"^note\s*:\s*where there are",
    r"^rounding", r"^errors in", r"^format and accuracy", r"^the markscheme",
    r"^diagrams$", r"^penalt", r"^mathematical notation", r"examiners", r"^samples$", r"part marks",
    r"^accuracy$", r"^the following illustrates", r"^using the markscheme",
    r"^examples of", r"^end of examples", r"^marks allocated", r"^calculator penalties",
)]
OPTION_WORDS = ("statistic", "probability", "sets", "relations", "groups", "algebra", "discrete",
                "graph", "analysis", "approximation", "geometry", "conic", "series", "differential",
                "calculus", "trees")
OCR_DIGIT = str.maketrans({"l": "1", "I": "1", "|": "1", "i": "1", "O": "0", "o": "0", "S": "5",
                           "s": "5", "B": "8", "Z": "2", "z": "2", "g": "9", "q": "9", "A": "4"})


# paper codes as OCR reads them: "N96/510/H(2)", "M96\\S10H(2)", "N99/510/H(1)M"
SCAN_CODE_RE = re.compile(r"^[MNH]\s?[0-9A-Z]{2,3}\s*[/\\|(]?\s*[5S][1lI][0O]\s*[/\\|(]?\s*H", re.I)
MARKSY = re.compile(r"marks?\b|\[|\]|^\(?[a-z]{1,3}\)|[AMR]\d|total", re.I)
# a markscheme / question-paper marks annotation: "[3 marks]", "Total [7 marks]", "(M1)(A1)", "(C6)", "AG"
MARKLIKE = re.compile(r"marks?\b|\[\s*\d|\btotal\b|\(\s*[ACMRN]\s*[0-9l]\s*\)|(?<![A-Za-z])[AMRN][0-9]\b|\bAG\b|\bN[0-9]\b", re.I)
# a line that is nothing but a marks annotation: "[6 marks]", "Total [7 marks]", "(M1)(A1)", "(C3)"
MARKONLY = re.compile(r"^\s*(?:total\s*)?\[\s*\d{1,3}\s*marks?\s*\]\s*\.?$|^\s*(?:\(?\s*[ACMRNG]\s*\d\s*\)?\s*)+$", re.I)
# notices on blank / answer-free pages; matched against a page line joined with the lines just below it
NOTICE_RE = re.compile(
    r"^(?:please\s+)?do not write (?:solutions\s+)?on this page\.?"
    r"(?:\s*(?:answers written|any working) on this page will not be marked\.?)?$"
    r"|^answers written on this page will not be marked\.?$"
    r"|^any working on this page will not be marked\.?$"
    r"|^(?:this page (?:is )?intentionally left )?blank page\.?$", re.I)


OCR_CONFUSE = {"1": "74", "7": "12", "4": "1", "3": "85", "8": "3605", "5": "638", "6": "58", "0": "86",
               "2": "7", "9": "8"}


class Line:
    __slots__ = ("x0", "y0", "x1", "y1", "text", "bold", "conf", "kind", "page")

    def __init__(self, x0, y0, x1, y1, text, bold=False, conf=100.0, page=0):
        self.x0, self.y0, self.x1, self.y1 = x0, y0, x1, y1
        self.text = text
        self.bold = bold
        self.conf = conf
        self.kind = "text"      # text | dots | ignore | header | footer
        self.page = page

    @property
    def yc(self):
        return (self.y0 + self.y1) / 2

    def __repr__(self):
        return f"L(p{self.page} {self.x0:.0f},{self.y0:.0f} {self.kind} {self.text[:40]!r})"


class Page:
    def __init__(self, pno, W, H):
        self.pno, self.W, self.H = pno, W, H
        self.scan = False
        self.lines: list[Line] = []
        self.images: list[fitz.Rect] = []
        self.draws: list[tuple[fitz.Rect, str]] = []
        self.body_top = 0.0
        self.body_bot = H
        self.masks: list[fitz.Rect] = []
        self.cuts: list[float] = []          # y where an answer area ("Working:" box) starts
        self._hf = (False, False)
        self.tail_y: float | None = None     # boilerplate (References...) from here to page end
        # boxes of glyphs that carry no text (bracket / brace pieces of tall vectors and matrices)
        self.glyphs: list[fitz.Rect] = []
        self.foreign = False                 # page belongs to another paper (appended to the PDF)
        self.notice_only = False             # blank page carrying only "do not write on this page"


# ----------------------------------------------------------------------------- OCR

def _file_key(path: str) -> str:
    st = os.stat(path)
    return hashlib.sha1(f"{path}|{st.st_size}|{int(st.st_mtime)}".encode()).hexdigest()[:16]


def ocr_page(path: str, page: fitz.Page) -> list[Line]:
    OCR_CACHE.mkdir(parents=True, exist_ok=True)
    cache = OCR_CACHE / f"{_file_key(path)}_{page.number}.tsv"
    if cache.exists():
        tsv = cache.read_text()
    else:
        pix = page.get_pixmap(dpi=OCR_DPI, colorspace=fitz.csGRAY, alpha=False)
        png = pix.tobytes("png")
        env = dict(os.environ, OMP_THREAD_LIMIT="1")
        r = subprocess.run(["tesseract", "stdin", "stdout", "--psm", "3", "-l", "eng", "tsv"],
                           input=png, capture_output=True, env=env, timeout=180)
        tsv = r.stdout.decode("utf-8", "replace")
        tmp = cache.with_suffix(".tmp%d" % os.getpid())
        tmp.write_text(tsv)
        tmp.replace(cache)
    k = 72.0 / OCR_DPI
    groups: dict[tuple, list] = {}
    for row in tsv.splitlines()[1:]:
        f = row.split("\t")
        if len(f) < 12 or f[0] != "5":
            continue
        txt = f[11].strip()
        conf = float(f[10])
        if not txt or conf < 0:
            continue
        key = (int(f[2]), int(f[3]), int(f[4]))
        x, y, w, h = (int(v) for v in f[6:10])
        groups.setdefault(key, []).append((x, y, x + w, y + h, txt, conf))
    lines = []
    gap_px = 70 * OCR_DPI / 72.0
    segs = []
    for key, ws in groups.items():
        ws.sort()
        # drop words that are pure noise
        good = [w for w in ws if w[5] > 15 or len(w[4]) > 2]
        # leading/trailing junk (binding holes, scanner borders)
        while good and (not re.search(r"[A-Za-z0-9]", good[0][4]) or (
                good[0][5] < 35 and len(good[0][4]) <= 2 and not re.match(r"^\d{1,2}\.?$", good[0][4]))):
            good.pop(0)
        while good and not re.search(r"[A-Za-z0-9()\[\]]", good[-1][4]):
            good.pop()
        # split at very wide gaps (marks column, separate number token stays with its line)
        cur = []
        for w in good:
            if cur and w[0] - cur[-1][2] > gap_px:
                segs.append(cur)
                cur = []
            cur.append(w)
        if cur:
            segs.append(cur)
    for good in segs:
        if not good:
            continue
        x0 = min(w[0] for w in good) * k
        y0 = min(w[1] for w in good) * k
        x1 = max(w[2] for w in good) * k
        y1 = max(w[3] for w in good) * k
        text = " ".join(w[4] for w in good)
        conf = sum(w[5] for w in good) / len(good)
        ln = Line(x0, y0, x1, y1, text, False, conf, page.number)
        lines.append(ln)
    lines.sort(key=lambda l: (l.y0, l.x0))
    return lines


def strip_ocr(path: str, page: fitz.Page, x0: float, x1: float) -> list[tuple]:
    """OCR a narrow vertical strip (the question-number column) - finds numbers that full-page
    OCR misses.  Returns [(x0, y0, x1, y1, text, conf)] in PDF points."""
    OCR_CACHE.mkdir(parents=True, exist_ok=True)
    x0, x1 = max(0, int(x0)), min(int(page.rect.width), int(x1))
    out = []
    for psm in ("4", "6", "11"):
        cache = OCR_CACHE / f"{_file_key(path)}_{page.number}_s{x0}-{x1}_{psm}.tsv"
        if cache.exists():
            tsv = cache.read_text()
        else:
            pix = page.get_pixmap(dpi=OCR_DPI, colorspace=fitz.csGRAY, alpha=False,
                                  clip=fitz.Rect(x0, 0, x1, page.rect.height))
            env = dict(os.environ, OMP_THREAD_LIMIT="1")
            r = subprocess.run(["tesseract", "stdin", "stdout", "--psm", psm, "-l", "eng", "tsv"],
                               input=pix.tobytes("png"), capture_output=True, env=env, timeout=120)
            tsv = r.stdout.decode("utf-8", "replace")
            tmp = cache.with_suffix(".tmp%d" % os.getpid())
            tmp.write_text(tsv)
            tmp.replace(cache)
        k = 72.0 / OCR_DPI
        for row in tsv.splitlines()[1:]:
            f = row.split("\t")
            if len(f) < 12 or f[0] != "5" or not f[11].strip():
                continue
            x, y, w, h = (int(v) for v in f[6:10])
            out.append((x0 + x * k, y * k, x0 + (x + w) * k, (y + h) * k, f[11].strip(), float(f[10])))
    return out


# ----------------------------------------------------------------------------- page analysis

def _text_lines(page: fitz.Page, masks: list, glyphs: list | None = None) -> list[Line]:
    out = []
    d = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE | fitz.TEXT_MEDIABOX_CLIP)
    for b in d["blocks"]:
        if b.get("type") != 0:
            continue
        for l in b["lines"]:
            spans = [s for s in l["spans"] if s["text"].strip()]
            if not spans:
                continue
            real = []
            for s in spans:
                if is_dots(s["text"]):
                    masks.append(fitz.Rect(s["bbox"]))
                else:
                    real.append(s)
            if not real:
                bb = fitz.Rect(l["bbox"])
                ln = Line(bb.x0, bb.y0, bb.x1, bb.y1, "...", False, 100, page.number)
                ln.kind = "dots"
                out.append(ln)
                continue
            x0 = min(s["bbox"][0] for s in real)
            y0 = min(s["bbox"][1] for s in real)
            x1 = max(s["bbox"][2] for s in real)
            y1 = max(s["bbox"][3] for s in real)
            text = norm("".join(s["text"] for s in real))
            if not text:
                # bracket pieces (Symbol font, mapped away by norm) still occupy the row
                if glyphs is not None:
                    glyphs.append(fitz.Rect(x0, y0, x1, y1))
                continue
            f0 = real[0]
            bold = bool(f0["flags"] & 16) or "bold" in f0["font"].lower()
            out.append(Line(x0, y0, x1, y1, text, bold, 100, page.number))
    out.sort(key=lambda l: (round(l.y0), l.x0))
    return out


def _classify_draw(d) -> str:
    r = d["rect"]
    w, h = r.width, r.height
    dashes = d.get("dashes") or ""
    if dashes and not dashes.startswith("[]") and h < 2:
        return "dash"
    if dashes and not dashes.startswith("[]") and w < 2:
        return "vdash"
    if h <= 2.5 and w >= 2.5:
        return "hline"
    if w <= 2.5 and h >= 2.5:
        return "vline"
    return "shape"


class Doc:
    """Analysed PDF (question paper or markscheme)."""

    def __init__(self, path: str, is_ms: bool = False):
        self.path = path
        self.is_ms = is_ms
        self.doc = fitz.open(path)
        self.pages: list[Page] = []
        self.ocr = False
        need_ocr = []
        for pg in self.doc:
            P = Page(pg.number, pg.rect.width, pg.rect.height)
            txt = pg.get_text("text")
            imgs = pg.get_image_info()
            area = P.W * P.H
            big_img = sum(abs(fitz.Rect(i["bbox"]) & pg.rect) for i in imgs) > 0.5 * area
            if len(txt.strip()) < 15 and big_img:
                P.scan = True
                need_ocr.append(pg.number)
            else:
                P.lines = _text_lines(pg, P.masks, P.glyphs)
                P.images = [fitz.Rect(i["bbox"]) & pg.rect for i in imgs]
                P.images = [r for r in P.images if not r.is_empty and r.width > 3 and r.height > 3]
                try:
                    draws = pg.get_drawings()
                except Exception:
                    draws = []
                for dd in draws:
                    r = fitz.Rect(dd["rect"])
                    if r.is_empty and r.width == 0 and r.height == 0:
                        continue
                    P.draws.append((r, _classify_draw(dd)))
            self.pages.append(P)
        if need_ocr:
            self.ocr = True
            with ThreadPoolExecutor(8) as ex:
                res = list(ex.map(lambda n: ocr_page(path, fitz.open(path)[n]), need_ocr))
            for n, lines in zip(need_ocr, res):
                self.pages[n].lines = lines
        self._headers_footers()
        self._xrange()
        for P in self.pages:
            self._page_masks(P)

    # -- running headers/footers -------------------------------------------------------------
    def _headers_footers(self):
        npg = len(self.pages)
        top_cnt: dict[str, int] = {}
        bot_cnt: dict[str, int] = {}

        def key(t):
            return re.sub(r"\d+", "#", t.lower())[:60]

        for P in self.pages:
            seen_t, seen_b = set(), set()
            for l in P.lines:
                if l.y1 < 0.1 * P.H:
                    seen_t.add(key(l.text))
                elif l.y0 > 0.9 * P.H:
                    seen_b.add(key(l.text))
            for k in seen_t:
                top_cnt[k] = top_cnt.get(k, 0) + 1
            for k in seen_b:
                bot_cnt[k] = bot_cnt.get(k, 0) + 1
        thr = max(2, 0.3 * npg)
        qlike = re.compile(r"^(#\.?|\[maximum.*|\(?[a-z]{1,3}\).*|question.*|section.*|\(question.*)$")
        for P in self.pages:
            top, bot = 0.0, P.H
            for l in P.lines:
                t = l.text
                k = key(t)
                if l.y1 < 0.1 * P.H:
                    if any(r.search(t) for r in HEADER_RES) or (
                            top_cnt.get(k, 0) >= thr and not qlike.match(k) and l.y1 < 0.075 * P.H
                            and not MARKSY.search(k)):
                        l.kind = "header"
                        top = max(top, l.y1)
                elif l.y0 > 0.9 * P.H:
                    if (any(r.search(t) for r in HEADER_RES)
                            or (any(r.search(t) for r in FOOTER_EXTRA_RES) and (l.y0 > 0.92 * P.H or not t.isdigit()))
                            or (bot_cnt.get(k, 0) >= thr and not qlike.match(k) and l.y0 > 0.935 * P.H
                                and not MARKSY.search(k))):
                        l.kind = "footer"
                # OCR: page numbers like "- 4 -" may be read with junk; be tolerant in the top band
                if P.scan and l.kind == "text" and l.y1 < 0.075 * P.H and len(l.text) < 25:
                    l.kind = "header"
                    top = max(top, l.y1)
                if P.scan and l.kind == "text" and l.y0 > 0.85 * P.H and re.match(r"^[-–(]?\s*\d{1,2}\s*[-–)]?$", l.text) \
                        and 0.3 * P.W < (l.x0 + l.x1) / 2 < 0.7 * P.W:
                    l.kind = "footer"
                # (a "Total [21 marks]" / "(A1)" line at the bottom of a scanned markscheme page is content)
                if P.scan and l.kind == "text" and l.y0 > 0.93 * P.H and len(l.text) < 25 \
                        and not MARKLIKE.search(l.text):
                    l.kind = "footer"
                if P.scan and l.kind == "text" and l.y0 > 0.6 * P.H and (
                        re.search(r"turn over|^[A-Z]{0,3}\d{2,4}\s*[-.–]\s*\d{3,5}\]?$", l.text, re.I)
                        or any(r.search(l.text) for r in HEADER_RES) or SCAN_CODE_RE.match(l.text)):
                    l.kind = "footer"
                if P.scan and l.kind == "text" and l.y1 < 0.15 * P.H and SCAN_CODE_RE.match(l.text):
                    l.kind = "header"
                    top = max(top, l.y1)

            # a footer has no page content below it or beside it: a fraction's denominator or a lone
            # "3" at the bottom of a markscheme page is not a page number, a table cell "140-150" or an
            # OCR'd "©" in the middle of a scanned page is not a paper code
            def real(o):
                if o.kind != "text" or any(r.search(o.text) for r in HEADER_RES):
                    return False
                if P.scan:
                    return o.conf >= 50 and len(re.findall(r"[A-Za-z0-9]", o.text)) >= 3
                # (a lone control character such as "\x08" is no page content)
                return o.x1 > 0 and bool(re.search(r"[^\x00-\x20\x7f\ufffd]", o.text))

            def vover(a0, a1, b0, b1):
                return min(a1, b1) - max(a0, b0)

            changed = True
            while changed:
                changed = False
                body_text = [o for o in P.lines if real(o)]
                for l in P.lines:
                    if l.kind != "footer":
                        continue
                    if P.scan:
                        below = any(o.yc > l.y1 + 1 for o in body_text)
                    else:
                        below = any(o.y0 > l.y1 - 1 for o in body_text)
                    beside = any(vover(o.y0, o.y1, l.y0, l.y1) > 2.0 for o in body_text)
                    if below or beside:
                        l.kind = "text"
                        changed = True
            body_text = [o for o in P.lines if real(o)]
            for l in P.lines:
                if l.kind == "footer":
                    bot = min(bot, l.y0)

            def nothing_below(y):
                return P.scan or not any(o.y0 > y - 1 for o in body_text)

            def beside_text(r):
                # a rule, box or picture on the same rows as page text is content (a fraction bar, the
                # frame of a note, an equation image, a "Total [7 marks]" highlight)
                return any(r.y0 <= o.y1 - 1 and r.y1 >= o.y0 + 1 for o in body_text)

            def inline_top(r):
                # a small image / rule in the top band that belongs to a body line reaching below it
                return any(r.y0 <= o.y1 - 1 and r.y1 >= o.y0 + 1 and o.y1 > r.y1 + 1 for o in body_text)

            for r in P.images:
                if r.y0 > 0.88 * P.H and r.height < 0.1 * P.H and nothing_below(r.y1) and not beside_text(r):
                    bot = min(bot, r.y0)
                elif r.y1 < 0.1 * P.H and r.height < 0.1 * P.H and not inline_top(r):
                    top = max(top, r.y1)
            # vector barcodes / crop marks (dashed rules are the hatching of the page margins)
            for r, c in P.draws:
                if r.height > 0.1 * P.H or r.x1 < 0 or r.x0 > P.W:
                    continue
                if r.y0 > 0.9 * P.H and r.y1 <= P.H + 5 and nothing_below(r.y1) and not beside_text(r) \
                        and c not in ("dash", "vdash"):
                    bot = min(bot, r.y0)
                elif r.y1 < 0.07 * P.H and r.y0 >= -5 and not inline_top(r):
                    top = max(top, r.y1)
            # never let the body box collapse
            P.body_top = min(top + 1.5, 0.2 * P.H) if top > 0 else 0.03 * P.H
            P.body_bot = max(bot - 1.5, 0.8 * P.H) if bot < P.H else 0.97 * P.H
            P._hf = (top > 0, bot < P.H)
        # scans: OCR misses some page numbers / codes; reuse the typical band of the other pages
        scans = [P for P in self.pages if P.scan]
        if scans:
            tops = sorted(P.body_top / P.H for P in scans if P._hf[0])
            bots = sorted(P.body_bot / P.H for P in scans if P._hf[1])
            for P in scans:
                if not P._hf[0] and len(tops) >= 2:
                    P.body_top = max(P.body_top, min(tops[len(tops) // 2], 0.15) * P.H)
                if not P._hf[1] and len(bots) >= 2:
                    lim = max(bots[len(bots) // 2], 0.85) * P.H
                    # ... but never cut through a line of real page content below that band
                    content = [o.y1 for o in P.lines if o.kind == "text" and o.yc > lim and o.conf >= 50
                               and (len(o.text) >= 25 or MARKLIKE.search(o.text) or "=" in o.text)
                               and len(re.findall(r"[A-Za-z0-9]", o.text)) >= 3]
                    if content:
                        lim = min(max(content) + 2.0, 0.97 * P.H)
                    P.body_bot = min(P.body_bot, lim)

    def _xrange(self):
        xs0, xs1 = [], []
        for P in self.pages:
            for l in P.lines:
                if l.kind != "text" or not (P.body_top <= l.yc <= P.body_bot):
                    continue
                if P.scan and (l.conf < 60 or len(l.text) < 3):
                    continue
                if l.x0 > 0.02 * P.W:
                    xs0.append(l.x0)
                if l.x1 < 0.98 * P.W:
                    xs1.append(l.x1)
        W = max(P.W for P in self.pages)
        if xs0:
            xs0.sort()
            xs1.sort()
            # robust: ignore a few stray outliers
            lo = xs0[min(len(xs0) - 1, max(0, len(xs0) // 200))]
            hi = xs1[max(0, len(xs1) - 1 - len(xs1) // 200)]
        else:
            lo, hi = 0.07 * W, 0.93 * W
        pad = 14 if self.ocr else 10
        self.xL = max(0.02 * W, lo - pad)
        self.xR = min(0.98 * W, hi + pad)
        # left column of question numbers is estimated later

    # -- masks / answer areas ----------------------------------------------------------------
    def _page_masks(self, P: Page):
        tail = None
        for l in P.lines:
            if l.kind != "text":
                continue
            t = l.text
            if any(r.search(t) for r in IGNORE_RES):
                l.kind = "ignore"
                P.masks.append(fitz.Rect(l.x0, l.y0, l.x1, l.y1))
            elif is_dots(t):
                l.kind = "dots"
            if l.kind == "text" and any(r.search(t) for r in TAIL_RES) and l.y0 > P.body_top:
                if tail is None or l.y0 < tail:
                    tail = l.y0
        if tail is not None:
            P.tail_y = tail - 2
        # notices broken over several lines ("Answers written on this page will not" / "be marked.")
        tl = sorted((l for l in P.lines if l.kind == "text"), key=lambda l: (l.y0, l.x0))
        for i, l in enumerate(tl):
            if l.kind == "text" and NOTICE_RE.match(l.text):
                l.kind = "ignore"
                P.masks.append(fitz.Rect(l.x0, l.y0, l.x1, l.y1))
                continue
            grp = [l]
            for o in tl[i + 1:]:
                if o.y0 > grp[-1].y1 + 6 or len(grp) >= 3:
                    break
                if o.y0 < grp[-1].y0 + 4 or o.x1 < l.x0 or o.x0 > l.x1:
                    continue
                grp.append(o)
                if NOTICE_RE.match(norm(" ".join(g.text for g in grp))):
                    for g in grp:
                        g.kind = "ignore"
                        P.masks.append(fitz.Rect(g.x0, g.y0, g.x1, g.y1))
                    break
        # a blank page that only says "Please do not write on this page / Answers written on this page
        # will not be marked" is never part of a question (its frame is drawn as loose rules)
        body = [l for l in P.lines if P.body_top <= l.yc <= P.body_bot]
        P.notice_only = (not P.scan and not any(l.kind == "text" for l in body) and not P.images
                         and any(l.kind == "ignore" and re.search(r"write (solutions )?on this page|will not be marked|"
                                                                  r"blank page", l.text, re.I) for l in body))
        # frames around "do not write on this page" notices
        for r, c in P.draws:
            if c != "shape" or r.width < 40 or r.height < 15 or r.height > 0.6 * P.H:
                continue
            inside = [l for l in P.lines if r.contains(fitz.Point((l.x0 + l.x1) / 2, l.yc))]
            if inside and all(l.kind in ("ignore", "dots") for l in inside) and any(l.kind == "ignore" for l in inside):
                P.masks.append(fitz.Rect(r.x0 - 2, r.y0 - 2, r.x1 + 2, r.y1 + 2))
        vdash = [r for r, c in P.draws if c == "vdash"]
        colw = self.xR - self.xL
        for r, c in P.draws:
            # dashed answer lines; the hatched page margins are dashed too but lie outside the column,
            # and dashed grid lines of a sketch grid are crossed by dashed verticals
            if c == "dash" and r.x0 >= self.xL - 6 and r.x1 <= self.xR + 6 and r.width >= 0.6 * colw \
                    and not any(r.x0 - 1 <= v.x0 <= r.x1 + 1 and v.y0 - 1 <= r.y0 <= v.y1 + 1 for v in vdash):
                P.masks.append(fitz.Rect(r.x0 - 1, r.y0 - 1.5, r.x1 + 1, r.y1 + 1.5))
        # framed answer boxes made of two tall verticals (2019+ papers)
        verts = [r for r, c in P.draws if c == "vline" and 60 <= r.height < 0.9 * P.H
                 and r.y0 >= 0.03 * P.H and r.y1 <= 0.97 * P.H and self.xL - 30 <= r.x0 <= self.xR + 30]
        boxes = []
        for i, a in enumerate(verts):
            for b in verts[i + 1:]:
                if abs(a.y0 - b.y0) < 4 and abs(a.y1 - b.y1) < 4 and abs(a.x0 - b.x0) > 150:
                    bx = fitz.Rect(min(a.x0, b.x0), min(a.y0, b.y0), max(a.x1, b.x1), max(a.y1, b.y1))
                    if not any(abs(bx.y0 - o.y0) < 2 and abs(bx.y1 - o.y1) < 2 for o in boxes):
                        boxes.append(bx)
        for bx in boxes:
            ok = True
            inner = fitz.Rect(bx.x0 + 3, bx.y0 + 3, bx.x1 - 3, bx.y1 - 3)
            for l in P.lines:
                if l.kind == "text" and inner.contains(fitz.Point((l.x0 + l.x1) / 2, l.yc)):
                    if not ANSWERISH_RE.match(l.text):
                        ok = False
                        break
            if ok:
                for r in P.images:
                    if inner.intersects(r) and abs(r & inner) > 20:
                        ok = False
                        break
            if ok:
                nv = 0
                for r, c in P.draws:
                    if c in ("shape", "vdash") and inner.intersects(r) and abs(r & inner) > 30 \
                            and abs(r) < 0.5 * P.W * P.H and not r.contains(bx):
                        ok = False
                        break
                    if c == "vline" and inner.contains(r):
                        nv += 1
                if nv > 4:
                    ok = False
            if ok:
                P.masks.append(fitz.Rect(bx.x0 - 2.5, bx.y0 - 2.5, bx.x1 + 2.5, bx.y1 + 2.5))
                for l in P.lines:
                    if l.kind == "text" and bx.contains(fitz.Point((l.x0 + l.x1) / 2, l.yc)):
                        l.kind = "ignore"
        # "Working:" boxes (1990s-2005 paper 1): everything below the label belongs to the box
        if not self.is_ms:
            for l in P.lines:
                if l.kind == "text" and WORKING_RE.match(l.text) and l.x0 < self.xL + 0.3 * (self.xR - self.xL):
                    cut = l.y0 - (12 if P.scan else 9)
                    # snap to the box's top border if there is one just above
                    for r, c in P.draws:
                        if c in ("hline", "shape") and r.width > 100 and l.y0 - 22 < r.y1 <= l.y0 + 1:
                            cut = min(cut, r.y0 - 1.5)
                    P.cuts.append(cut)

    # -- content queries ----------------------------------------------------------------------
    def body_lines(self, pno: int, y0: float = -1e9, y1: float = 1e9, kinds=("text",)):
        P = self.pages[pno]
        return [l for l in P.lines if l.kind in kinds and y0 <= l.yc <= y1
                and P.body_top - 2 <= l.yc <= P.body_bot + 2]

    def all_text(self, pno: int) -> str:
        return "\n".join(l.text for l in self.pages[pno].lines)


# ----------------------------------------------------------------------------- question chain

class Cand:
    __slots__ = ("page", "y0", "y1", "x0", "num", "score", "line", "kind", "weak")

    def __init__(self, line: Line, num: int, score: float, kind: str, weak=False):
        self.page, self.y0, self.y1, self.x0 = line.page, line.y0, line.y1, line.x0
        self.num, self.score, self.line, self.kind, self.weak = num, score, line, kind, weak

    @property
    def pos(self):
        return (self.page, self.y0)

    def __repr__(self):
        return f"C(p{self.page} y{self.y0:.0f} x{self.x0:.0f} #{self.num} s{self.score:.1f}{' weak' if self.weak else ''})"


NUM_RE = re.compile(r"^(\d{1,2})\s*\.(?:\s|$|[(\[])")
NUM_ALONE_RE = re.compile(r"^(\d{1,2})\s*\.?$")
QWORD_RE = re.compile(r"^QUESTION\s+(\d{1,2})\s*\.?$", re.I)
OCR_NUM_RE = re.compile(r"^([0-9lI|OoSZB]{1,2})\s*[.,:;](?=\s|$|[(\[])")


def section_heads(D: Doc) -> list[tuple[int, float, str, Line]]:
    out = []
    for P in D.pages:
        if P.foreign:
            continue
        for l in P.lines:
            if l.kind not in ("text",):
                continue
            t = l.text.strip()
            m = SECTION_RE.match(t)
            if not m and P.scan:
                m = re.match(r"^SECT[I1l]ON\s+([A-E])\b.{0,3}$", t, re.I)
            if m and (P.body_top - 2 <= l.yc <= P.body_bot + 2):
                out.append((P.pno, l.y0, m.group(1).upper(), l))
    return out


def find_candidates(D: Doc, ms_mode: bool, fm_end=(0, 0.0)) -> list[Cand]:
    raw = []
    for P in D.pages:
        if P.foreign:
            continue
        lines = [l for l in P.lines if l.kind == "text" and P.body_top - 2 <= l.yc <= P.body_bot + 2]
        for i, l in enumerate(lines):
            t = l.text.strip()
            if P.scan:
                t = re.sub(r"^[\"'‘’“”|.,:;_~`»«*-]+\s*", "", t)
            num, kind, weak = None, "", False
            m = NUM_RE.match(t)
            if m:
                num, kind = int(m.group(1)), "dot"
            elif QWORD_RE.match(t):
                num, kind = int(QWORD_RE.match(t).group(1)), "qword"
            elif re.match(r"^QUESTION\s+(\d{1,2})\b(?!.*contin)", t, re.I) and ms_mode and l.bold:
                num, kind = int(re.match(r"^QUESTION\s+(\d{1,2})", t, re.I).group(1)), "qword"
            elif NUM_ALONE_RE.match(t) and l.bold and not P.scan:
                num, kind = int(NUM_ALONE_RE.match(t).group(1)), "alone"
            elif P.scan:
                m = OCR_NUM_RE.match(t)
                if m:
                    s = m.group(1).translate(OCR_DIGIT)
                    if s.isdigit():
                        num, kind, weak = int(s), "ocr", not m.group(1).isdigit()
                elif re.match(r"^\d{1,2}$", t.split(" ")[0]):
                    # "3 [Maximum mark: 9]" / "3 z=-1+3i" with the period lost
                    parts = t.split(" ", 1)
                    nxt = parts[1] if len(parts) > 1 else ""
                    if (MAXMARK_RE.search(nxt) or re.match(r"^[\[(]", nxt) or ms_mode
                            or (not nxt and l.conf > 60)):
                        num, kind, weak = int(parts[0]), "ocr", True
            if num is None or num < 1 or num > 40:
                continue
            if ms_mode and (P.pno, l.y0) < fm_end:
                continue
            # [Maximum mark] on the same line or right below/right of it
            mm = bool(MAXMARK_RE.search(t))
            if not mm:
                for o in lines[max(0, i - 3): i + 4]:
                    if o is not l and abs(o.y0 - l.y0) < 22 and o.x0 >= l.x0 and MAXMARK_RE.search(o.text):
                        mm = True
                        break
            sc = 1.0 + (1.0 if l.bold else 0) + (2.0 if mm else 0) + (0.5 if kind in ("dot", "qword") else 0)
            if P.scan:
                sc += 0.5 if l.conf > 70 else 0
                if weak:
                    sc -= 0.7
            raw.append(Cand(l, num, sc, kind, weak))
    if not raw:
        return []
    # the question-number column: the x where most good candidates sit
    xs = sorted(c.x0 for c in raw if c.kind in ("dot", "qword", "alone", "ocr"))
    best_x, best_n = xs[0], 0
    for x in xs:
        n = sum(1 for y in xs if x - 1 <= y <= x + 6)
        if n > best_n:
            best_x, best_n = x, n
    # prefer the leftmost cluster if it is populated enough
    left = [x for x in xs if x <= best_x + 6]
    col = min(left) if left else best_x
    tol = 16 if D.ocr else 9
    # scans: the left margin moves from page to page, so measure it per page
    lm = {}
    for P in D.pages:
        if not P.scan or P.foreign:
            continue
        # left edge of real text on this page (binding holes / scanner borders produce junk lines)
        xs_p = sorted(l.x0 for l in P.lines if l.kind == "text" and l.conf > 60
                      and len(re.findall(r"[A-Za-z0-9]", l.text)) >= 3
                      and P.body_top <= l.yc <= P.body_bot and l.x0 > 15)
        if xs_p:
            lm[P.pno] = xs_p[0]
    refs = {}       # pno -> (lo, hi) window for the number column
    for pno, cl in list(lm.items()):
        P = D.pages[pno]
        have = [(c.num, c.y0) for c in raw if c.page == pno]
        toks = strip_ocr(D.path, D.doc[pno], max(15, cl - 75), cl + 30)
        strong = [c.x0 for c in raw if c.page == pno and c.kind in ("dot", "ocr") and not c.weak
                  and c.line.conf > 50 and re.match(r"^\d{1,2}\.(\s|$|[(\[])", c.line.text)
                  and c.x0 < 0.4 * P.W]
        page_toks = []
        for (x0, y0, x1, y1, t, conf) in toks:
            if not (P.body_top <= (y0 + y1) / 2 <= P.body_bot):
                continue
            t2 = re.sub(r"^[\"'‘’“”|,:;_~`»«*-]+", "", t)
            m = re.match(r"^([0-9lI|SOoZB]{1,2})([.,]?)$", t2)
            if not m:
                continue
            if m.group(1).isdigit() and m.group(2) and conf > 50:
                strong.append(x0)
            page_toks.append((x0, y0, x1, y1, t2, conf, m))
        if strong:
            col_p = min(strong)
            refs[pno] = (col_p - 12, col_p + 18)
        else:
            refs[pno] = (cl - 75, cl + 18)
        lo, hi = refs[pno]
        for (x0, y0, x1, y1, t2, conf, m) in page_toks:
            if x0 > hi or x0 < lo - (18 if (m.group(2) and conf > 40) else 0):
                continue
            sdig = m.group(1).translate(OCR_DIGIT)
            if not sdig.isdigit() or not (1 <= int(sdig) <= 40):
                continue
            if not m.group(1).isdigit() and conf < 60:
                continue
            num = int(sdig)
            if any(n == num and abs(y - y0) < 10 for n, y in have):
                continue
            if ms_mode and (pno, y0) < fm_end:
                continue
            ln = Line(x0, y0, x1, y1, t2, False, conf, pno)
            sc = 1.0 + (0.5 if m.group(2) else 0) + (0.5 if conf > 80 else 0) - (0.5 if not m.group(1).isdigit() else 0)
            raw.append(Cand(ln, num, sc, "strip", weak=not m.group(1).isdigit()))
            have.append((num, y0))
    out = []
    for c in raw:
        if c.page in refs:
            lo, hi = refs[c.page]
            if c.x0 > hi or c.x0 < lo:
                continue
            if c.x0 < lo + 18:
                c.score += 0.5
        else:
            if c.x0 < col - (25 if D.ocr else 12):
                continue
            if c.x0 > col + tol:
                # markschemes occasionally misplace a heading into the part column
                if ms_mode and c.kind == "dot" and c.line.bold and c.x0 <= col + 32:
                    c.score -= 1.0
                else:
                    continue
            if abs(c.x0 - col) < 4:
                c.score += 0.5
        out.append(c)
    # scans: digits are often misread (7->1, 8->3 ...); offer the confusable readings as weaker
    # alternatives so the chain can bridge a misread number
    alts = []
    for c in out:
        if not D.pages[c.page].scan:
            continue
        s_ = str(c.num)
        if len(s_) == 2 and s_[1] in "14":
            # "1." read as "14" / "11": the period became a digit
            alts.append(Cand(c.line, int(s_[0]), c.score - 1.3, c.kind, True))
        for i, ch in enumerate(s_):
            for rep in OCR_CONFUSE.get(ch, ""):
                n2 = int(s_[:i] + rep + s_[i + 1:])
                if 1 <= n2 <= 40 and n2 != c.num:
                    a = Cand(c.line, n2, c.score - 1.3, c.kind, True)
                    alts.append(a)
    out.extend(alts)
    out.sort(key=lambda c: (c.page, c.y0, -c.score))
    D.numcol = col
    return out


def best_chain(cands: list[Cand], heads, allow_gap: bool, expected: list[str] | None = None):
    """DP over candidates in reading order.  Returns list of (label, cand, gap_before)."""
    n = len(cands)
    if not n:
        return []
    head_pos = [(p, y) for p, y, _, _ in heads]

    def head_between(a: Cand, b: Cand):
        return any(a.pos < hp < b.pos for hp in head_pos)

    NEG = -1e9
    best = [NEG] * n
    prev = [-1] * n
    gapf = [False] * n
    for i, c in enumerate(cands):
        if c.num == 1:
            best[i] = c.score
        elif allow_gap and c.num == 2:
            best[i] = c.score - 2.5
            gapf[i] = True
        elif expected is not None and c.num > 1:
            # markscheme may legitimately miss the first questions (e.g. a different section start)
            best[i] = c.score - 3.0 - 0.5 * c.num
            gapf[i] = True
        for j in range(i):
            if best[j] == NEG:
                continue
            p = cands[j]
            if p.page == c.page and abs(p.y0 - c.y0) < 3:
                continue
            v = NEG
            g = False
            if c.num == p.num + 1:
                v = best[j] + c.score
            elif c.num == 1 and p.num >= 2 and head_between(p, c):
                v = best[j] + c.score
            elif allow_gap and p.num + 2 <= c.num <= p.num + 3:
                v = best[j] + c.score - 1.2 * (c.num - p.num - 1)
                g = True
            elif expected is not None and p.num + 2 <= c.num <= p.num + 4:
                v = best[j] + c.score - 1.5 * (c.num - p.num - 1)
                g = True
            if v > best[i]:
                best[i], prev[i], gapf[i] = v, j, g
    end = max(range(n), key=lambda i: (best[i], -i))
    if best[end] == NEG:
        return []
    path = []
    i = end
    while i >= 0:
        path.append(i)
        i = prev[i]
    path.reverse()
    chain = [(cands[i], gapf[i]) for i in path]
    # labels: if numbering restarts, prefix each block with its section letter
    restarts = any(chain[k][0].num == 1 for k in range(1, len(chain)))
    out = []
    for c, g in chain:
        label = str(c.num)
        if restarts:
            sec = None
            for p, y, s, _ in heads:
                if (p, y) < c.pos:
                    sec = s
            label = (sec or "") + label
        out.append((label, c, g))
    return out


def fm_end_pos(D: Doc) -> tuple[int, float]:
    """Position after the markscheme front matter (instructions to examiners)."""
    last = (0, 0.0)
    lim = min(len(D.pages), max(8, int(len(D.pages) * 0.6)))
    seen, misses = False, 0
    for P in D.pages[:lim]:
        hit = False
        nh = 0
        page_last = None
        # front matter is one contiguous run of pages: stop after two text pages without a hit
        if seen and misses >= 2:
            break
        for l in P.lines:
            if l.kind != "text" or len(l.text) > 70:
                continue
            # headings only: bold on text pages (question notes reuse words like "Follow through")
            if not P.scan and not l.bold and not re.match(r"^\d{1,2}\s*\.?\s+\S", l.text) \
                    and not re.match(r"^(instructions to examiners|abbreviations|this markscheme)", l.text, re.I):
                continue
            t = re.sub(r"^\d{1,2}\s*\.?\s*", "", l.text.strip())
            if any(r.match(t) for r in FM_RES):
                page_last = max(page_last or (0, 0.0), (P.pno, l.y1))
                nh += 1
        # scans: OCR text has no bold flag, so a lone keyword ("Follow through" in a note) is not
        # enough to start the front matter
        hit = nh >= (2 if (P.scan and not seen) else 1)
        if hit:
            last = max(last, page_last)
            seen, misses = True, 0
        elif sum(1 for l in P.lines if l.kind == "text") >= 5:
            misses += 1
    return last


# ----------------------------------------------------------------------------- regions

def section_of(pos, heads):
    sec = None
    for p, y, s, _ in heads:
        if (p, y) < pos:
            sec = s
    return sec


_FN_RE = re.compile(r"(arc)?(sin|cos|tan|sec|csc|cosec|cot)h?|log|ln|exp|lim|det|max|min", re.I)


def _fragment_text(t: str) -> bool:
    """A piece of a formula (a numerator, the top row of a vector, a superscript), not a line of prose
    and not a marks annotation of the previous question."""
    t = t.strip()
    return len(t) <= 16 and not MARKLIKE.search(t) and not re.search(r"[A-Za-z]{4,}", _FN_RE.sub(" ", t))


def row_top(D: Doc, c: Cand) -> float:
    """Top of the visual row that begins with question number c on a text page.  Tall maths in that
    row - column vectors and matrices (whose bracket pieces carry no text), fraction numerators,
    superscripts, vector arrows, an integral's upper limit, a note box or a graph beside the number -
    reaches above the number's own line and belongs to this question, not to the one before."""
    P = D.pages[c.page]
    colw = max(1.0, D.xR - D.xL)
    els = []        # (rect, may_join_when_only_close_above)
    for l in P.lines:
        # (a "Total [6 marks]" line ending just inside the number's line belongs to the question before)
        if l.kind == "text" and l.yc > P.body_top and not (MARKLIKE.search(l.text) and l.y1 < c.y1 - 2):
            els.append((fitz.Rect(l.x0, l.y0, l.x1, l.y1), _fragment_text(l.text) and l.x0 > c.x0 + 8))
    for r in P.glyphs:
        els.append((r, r.x0 > c.x0 + 8))
    # the box drawn around a "[6 marks]" total belongs to the question before
    boxed = [fitz.Rect(l.x0, l.y0, l.x1, l.y1) for l in P.lines if l.kind == "text" and MARKONLY.match(l.text)]

    def holds_marks(r):
        return any(r.contains(fitz.Point((b.x0 + b.x1) / 2, (b.y0 + b.y1) / 2)) for b in boxed)

    for r, k in P.draws:
        if k == "dash" or r.height > 0.3 * P.H or r.width > 0.6 * colw or r.x0 <= c.x0 + 3 or holds_marks(r):
            continue
        els.append((r, r.width < 0.4 * colw and r.height < 60))
    for r in P.images:
        if r.x0 > c.x0 + 3 and r.height < 0.5 * P.H and not holds_marks(r):
            els.append((r, r.height < 40 and r.width < 0.5 * colw))
    top = c.y0
    lim = c.y0 - 45
    for _ in range(8):
        new = top
        for r, frag in els:
            if r.y0 >= top - 0.3 or r.y0 < lim or r.y0 < P.body_top - 1:
                continue
            if r.y1 > top + 1.5 or (frag and r.y1 >= top - 4.0):
                new = min(new, r.y0)
        if new >= top:
            break
        top = new
    return top


def start_cut(D: Doc, c: Cand) -> float:
    """y where the region of a question beginning at candidate c starts (midway in the gap above)."""
    P = D.pages[c.page]
    if P.scan:
        return ink_cut_above(D, c.page, c.y0, c=c)
    # the visual row of the number may start higher (fraction numerators, tall matrices)
    top = row_top(D, c)
    above = [l.y1 for l in P.lines if l.kind in ("text", "dots", "ignore") and l.y0 < top - 3 and l.yc > P.body_top
             and (l.y1 <= top + 1.5 or (MARKLIKE.search(l.text) and l.y1 < c.y1 - 2))]
    for r, k in P.draws:
        if k != "dash" and r.y1 <= top + 1 and r.y0 < top - 1 and r.y1 > P.body_top and r.x1 > D.xL \
                and r.x0 < D.xR and r.height < 0.5 * P.H:
            above.append(r.y1)
    for r in P.glyphs + P.images:
        if r.y1 <= top + 1 and r.y0 < top - 3 and r.y1 > P.body_top and r.height < 0.5 * P.H:
            above.append(r.y1)
    pad = 5
    y = top - pad
    if above:
        g = max(above)
        if g > top - 2 * pad:
            y = (g + top) / 2
    return max(y, P.body_top)


def ink_cut_above(D: Doc, pno: int, y_top: float, max_up: float = 60.0, c: Cand | None = None) -> float:
    """Scans: find the blank band just above a line (whose box may be too low because of tall
    formulas / skew) and cut in its middle.  With the question-number candidate c, a small ink blob
    just above the line and right of the number (a fraction numerator or the top row of a vector that
    OCR did not read) is part of the line, so the walk continues above it."""
    P = D.pages[pno]
    y0 = max(P.body_top, y_top - max_up)
    if y_top - y0 < 4:
        return max(P.body_top, y_top - 3)
    clip = fitz.Rect(D.xL, y0, D.xR, y_top + 1)
    pix = D.doc[pno].get_pixmap(matrix=fitz.Matrix(2, 2), clip=clip, colorspace=fitz.csGRAY, alpha=False)
    a = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.stride)[:, :pix.width]
    e = 12
    a = a[:, e:max(e + 1, a.shape[1] - e)]
    inkm = a < 150
    ink = inkm.sum(axis=1) > 1          # (a thin numerator "1" is 2px wide)
    n = len(ink)
    colw = D.xR - D.xL

    def fragment(b_top, b_bot):
        """rows b_top..b_bot (2x pixels) hold one small piece of maths of this question's first line?"""
        if b_top <= 0 or c is None:
            return False
        cnt = inkm[b_top:b_bot + 1].sum(axis=0)
        cols = np.nonzero(cnt)[0]
        if not len(cols):
            return False
        # horizontal extent of the ink, ignoring isolated specks (scanner dirt at the margins)
        groups, g0 = [], cols[0]
        for a_, b_ in zip(cols[:-1], cols[1:]):
            if b_ - a_ > 20:
                groups.append((g0, a_))
                g0 = b_
        groups.append((g0, cols[-1]))
        groups = [(u, v) for u, v in groups if cnt[u:v + 1].sum() >= 8] or groups
        h = (b_bot - b_top + 1) / 2.0
        w = (groups[-1][1] - groups[0][0] + 1) / 2.0
        left = D.xL + (e + groups[0][0]) / 2.0
        if h > 12 or w > 0.4 * colw or left < c.x0 + 12:
            return False
        ya, yb = y0 + b_top / 2.0, y0 + (b_bot + 1) / 2.0
        for l in P.lines:
            if ya - 1 <= l.yc <= yb + 1 and l.kind == "text" and l.conf >= 40 and (
                    not _fragment_text(l.text) or l.x0 < c.x0 + 12):
                return False
        return True

    # walk up through the ink of the current row, then find a blank run of >= 3pt
    run = 0
    i = n - 1
    while i >= 0:
        if not ink[i]:
            run += 1
            if run >= 6:
                # extend to the full blank run
                j = i
                while j > 0 and not ink[j - 1]:
                    j -= 1
                bot_blank = i + run - 1
                if bot_blank - j + 1 <= 14 and j > 0:
                    # the ink block above the blank run (gaps of under 1.5pt inside it)
                    k, gap, b_bot = j - 1, 0, j - 1
                    while k >= 0:
                        gap = gap + 1 if not ink[k] else 0
                        if gap >= 3:
                            break
                        k -= 1
                    b_top = k + gap if k >= 0 else 0
                    if fragment(b_top, b_bot):
                        i, run = b_top - 1, 0
                        continue
                mid = (j + i + run) / 2.0
                return y0 + mid / 2.0
        else:
            run = 0
        i -= 1
    return max(P.body_top, y_top - 8)


_PAPER_NO = {"1": "1", "2": "2", "3": "3", "L": "1", "I": "1", "|": "1", "Z": "2"}


def page_paper_numbers(P: Page) -> set[str]:
    """Paper numbers named by the paper codes in a page's header / footer band:
    "N98/510/H(2)M" -> 2, "M07/5/MATHL/HP3/ENG/TZ1/XX/M+" -> 3, "M21/5/MATHX/AHP1/ENG/TZ2/XX/M" -> 1."""
    out = set()
    for l in P.lines:
        if not (l.kind in ("header", "footer") or l.y1 < 0.15 * P.H or l.y0 > 0.85 * P.H):
            continue
        t = l.text.upper().replace(" ", "")
        m = re.match(r"^[MN][0-9OIL]{2}[/\\|]?5[/\\|]MATH\w*[/\\|]A?HP([123])\b", t) or \
            re.match(r"^[MNH][0-9OILS]{2,3}[/\\|(]?[5S][1LI][0O][/\\|(]?H\(?([123LIZ|])\)", t)
        if m:
            out.add(_PAPER_NO[m.group(1)])
    return out


def mark_foreign_pages(D: Doc, paper: str | None):
    """Pages of another paper scanned into the same PDF (e.g. four Paper 2 markscheme pages after the
    Paper 1 markscheme): from a page whose code names another paper up to the next page that names
    this paper again.  Such pages are left out of every crop."""
    if paper not in ("1", "2", "3"):
        return
    nums = [page_paper_numbers(P) for P in D.pages]
    if sum(1 for s in nums if paper in s) < 2:
        return
    state = False
    for P, s in zip(D.pages, nums):
        if s:
            state = paper not in s
        P.foreign = state


def _is_cover(P: Page) -> bool:
    txt = " ".join(l.text for l in P.lines if l.kind == "text")
    n = sum(1 for l in P.lines if l.kind == "text")
    return n < 15 and bool(re.search(r"markscheme|mark scheme|confidential", txt, re.I))


def build_regions(D: Doc, starts: list[tuple[int, float]], stops: list[tuple[int, float]],
                  stop_at_cut=True):
    """starts: (page, y) of each question in order. Returns list of piece lists [(page,y0,y1)]."""
    last = len(D.pages) - 1
    regions = []
    for k, (sp, sy) in enumerate(starts):
        if k + 1 < len(starts):
            ep, ey = starts[k + 1]
        else:
            ep, ey = last, D.pages[last].H
        for st in sorted(stops):
            if (sp, sy + 2) < st < (ep, ey):
                ep, ey = st
                break
        pieces = []
        for p in range(sp, ep + 1):
            P = D.pages[p]
            if P.foreign:
                break
            if p != sp and P.notice_only:
                continue
            y0 = sy if p == sp else P.body_top
            y1 = ey if p == ep else P.body_bot
            y0 = max(y0, P.body_top)
            y1 = min(y1, P.body_bot)
            if P.tail_y is not None and P.tail_y > y0:
                y1 = min(y1, P.tail_y)
            ended = False
            if stop_at_cut:
                for cy in P.cuts:
                    if y0 + 8 < cy < y1:
                        y1 = cy
                        ended = True
                        break
            if y1 - y0 > 3:
                pieces.append((p, y0, y1))
            if ended:
                break
        regions.append(pieces)
    return regions


# ----------------------------------------------------------------------------- rendering

def render_piece(D: Doc, p: int, y0: float, y1: float, trim=True):
    """Render one page piece.  Returns (np.uint8 array, (y0_pt, y1_pt) actually kept) or None."""
    if not (0 <= p < len(D.pages)) or D.pages[p].foreign:
        return None
    P = D.pages[p]
    page = D.doc[p]
    # running headers/footers are always excluded, also for manual (override) regions
    y0, y1 = max(y0, P.body_top), min(y1, P.body_bot)
    if y1 - y0 < 2:
        return None
    # a line or note box that runs past the usual right edge of the text column ("Total [15 marks]"
    # set further right than everything else) widens this piece instead of being cut
    xr = D.xR
    if not P.scan:
        for l in P.lines:
            if l.kind == "text" and y0 <= l.yc <= y1 and l.x0 < D.xR and D.xR < l.x1 < P.W - 2:
                xr = max(xr, l.x1 + 4)
        for r, k in P.draws:
            if k in ("shape", "hline") and r.y0 >= y0 - 1 and r.y1 <= y1 + 1 and r.x0 < D.xR - 20 \
                    and D.xR < r.x1 < P.W - 2:
                xr = max(xr, r.x1 + 2)
    clip = fitz.Rect(D.xL, y0, xr, y1) & page.rect
    if clip.is_empty or clip.height < 2:
        return None
    pix = page.get_pixmap(matrix=fitz.Matrix(SCALE, SCALE), clip=clip, colorspace=fitz.csGRAY, alpha=False)
    a = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.stride)[:, :pix.width].copy()
    h, w = a.shape
    for m in P.masks:
        if not m.intersects(clip):
            continue
        r0 = int(max(0, (m.y0 - clip.y0) * SCALE))
        r1 = int(min(h, np.ceil((m.y1 - clip.y0) * SCALE)))
        c0 = int(max(0, (m.x0 - clip.x0) * SCALE))
        c1 = int(min(w, np.ceil((m.x1 - clip.x0) * SCALE)))
        if r1 > r0 and c1 > c0:
            a[r0:r1, c0:c1] = 255
    if P.scan:
        a[a > 200] = 255
        # blank the outermost columns (scanner borders, binding holes)
        e = int(6 * SCALE)
        a[:, :e] = 255
        a[:, w - e:] = 255
    ink = (a < (150 if P.scan else 200))
    if P.scan:
        rowcnt = ink.sum(axis=1)
        rows = rowcnt > 2
    else:
        rows = ink.any(axis=1)
    if not rows.any():
        return None
    if trim:
        idx = np.nonzero(rows)[0]
        top, bot = idx[0], idx[-1]
        if P.scan:
            # ignore isolated specks at the edges
            pass
        padpx = int(4 * SCALE)
        t0 = max(0, top - padpx)
        b1 = min(h, bot + padpx + 1)
        a = a[t0:b1]
        rows = rows[t0:b1]
        kept = (clip.y0 + t0 / SCALE, clip.y0 + b1 / SCALE)
    else:
        kept = (clip.y0, clip.y1)
    a = squeeze_blank(a, rows)
    return a, kept


def squeeze_blank(a, rows, maxgap=int(42 * SCALE), keep=int(22 * SCALE)):
    """Collapse long runs of blank rows (empty answer space) to `keep` rows."""
    blank = ~rows
    n = len(blank)
    keep_mask = np.ones(n, dtype=bool)
    i = 0
    while i < n:
        if blank[i]:
            j = i
            while j < n and blank[j]:
                j += 1
            if j - i > maxgap:
                s = i + keep // 2
                e = j - keep // 2
                keep_mask[s:e] = False
            i = j
        else:
            i += 1
    return a[keep_mask]


def stitch(arrs: list[np.ndarray]) -> Image.Image | None:
    arrs = [x for x in arrs if x is not None and x.size]
    if not arrs:
        return None
    W = max(x.shape[1] for x in arrs)
    gap = int(8 * SCALE)
    H = sum(x.shape[0] for x in arrs) + gap * (len(arrs) - 1)
    out = np.full((H, W), 255, dtype=np.uint8)
    y = 0
    for k, x in enumerate(arrs):
        out[y:y + x.shape[0], :x.shape[1]] = x
        y += x.shape[0]
        if k + 1 < len(arrs):
            # faint dotted separator marks the page break
            out[y + gap // 2, ::6] = 200
            y += gap
    im = Image.fromarray(out, "L")
    if im.height > MAX_IMG_H:
        f = MAX_IMG_H / im.height
        im = im.resize((max(1, int(im.width * f)), MAX_IMG_H), Image.LANCZOS)
    return im


def render_region(D: Doc, pieces, trim=True):
    arrs, kept = [], []
    for p, y0, y1 in pieces:
        r = render_piece(D, p, y0, y1, trim)
        if r is None:
            continue
        arrs.append(r[0])
        kept.append((p, r[1][0], r[1][1]))
    return stitch(arrs), kept


def region_text(D: Doc, kept) -> str:
    out = []
    for p, y0, y1 in kept:
        ls = [l for l in D.pages[p].lines if l.kind == "text" and y0 - 1 <= l.yc <= y1 + 1
              and l.x1 > D.xL and l.x0 < D.xR]
        ls.sort(key=lambda l: (round(l.yc / 4), l.x0))
        rows, cur, cy = [], [], None
        for l in ls:
            if cy is None or abs(l.yc - cy) > 4:
                if cur:
                    rows.append(" ".join(x.text for x in cur))
                cur, cy = [l], l.yc
            else:
                cur.append(l)
        if cur:
            rows.append(" ".join(x.text for x in cur))
        out.extend(rows)
    return "\n".join(out).strip()


def diagram_share(D: Doc, kept) -> float:
    """Fraction of the kept area covered by pictures / non-trivial vector graphics."""
    tot, art = 0.0, 0.0
    for p, y0, y1 in kept:
        P = D.pages[p]
        if P.scan:
            return 0.0
        clip = fitz.Rect(D.xL, y0, D.xR, y1)
        tot += abs(clip)
        rects = [r for r in P.images] + [r for r, c in P.draws if c in ("shape", "vdash")
                                          and abs(r) < 0.5 * P.W * P.H and r.width > 25 and r.height > 25]
        # merge overlapping rectangles roughly: grow clusters
        merged = []
        for r in sorted((r & clip for r in rects if r.intersects(clip)), key=lambda r: (r.y0, r.x0)):
            for m in merged:
                if m.intersects(r):
                    m |= r
                    break
            else:
                merged.append(fitz.Rect(r))
        art += sum(abs(m) for m in merged)
    return art / tot if tot else 0.0


def save_webp(im: Image.Image, path: Path):
    im.save(path, "WEBP", quality=WEBP_QUALITY, method=4)


# ----------------------------------------------------------------------------- marks

TOTALMARK_RE = re.compile(r"\[\s*Total\s*marks?\s*[:;.]?\s*(\d{1,3})\s*\]", re.I)


def parse_marks(text: str, default=None):
    m = TOTALMARK_RE.search(text)
    if m:
        return int(m.group(1))
    m = MAXMARK_RE.search(text)
    if m:
        return int(m.group(1))
    parts = [int(x) for x in PARTMARK_RE.findall(text)]
    if parts and sum(parts) <= 60:
        return sum(parts)
    return default


def ms_total(text: str):
    t = TOTAL_RE.findall(text)
    if t:
        return int(t[-1])
    parts = [int(x) for x in MSMARKS_RE.findall(text)]
    if parts:
        return sum(parts)
    return None


def ms_mark_estimate(text):
    """Mark total implied by a markscheme crop of an old paper 1 question: the (Cn) answer marks
    of each part, or else the sum of M/A/R marks; None if nothing usable."""
    if not text:
        return None
    if re.search(r"METHOD\s*2|\bOR\b|EITHER", text):
        return None
    cs = [int(x) for x in re.findall(r"\(C(\d)\)", text)]
    if cs:
        return sum(cs)
    mar = 0
    for tok in re.findall(r"(?<![\w])((?:\(?[AMRN]\d\)?)+)(?![\w])", text):
        mar += sum(int(x) for x in re.findall(r"[AMR](\d)", tok))
    return mar or None


def ms_consistent(text: str, marks):
    """True/False if the markscheme crop's mark annotations agree/disagree with the question's
    marks; None if undecidable."""
    if marks is None or not text:
        return None
    t = [int(x) for x in TOTAL_RE.findall(text)]
    if t:
        return t[-1] == marks or sum(t) == marks
    parts = [int(x) for x in MSMARKS_RE.findall(text)]
    if not parts:
        return None
    # alternative METHODs repeat the part total, so accept sum, max or last
    return marks in (sum(parts), max(parts), parts[-1]) or sum(parts) >= marks


def paper_total(D: Doc):
    for P in D.pages[:3]:
        txt = norm(" ".join(l.text for l in P.lines))
        m = re.search(r"maximum mark for this (?:examination )?paper is\s*\[?\s*(\d{2,3})", txt, re.I)
        if m:
            return int(m.group(1))
        m = re.search(r"\[\s*(\d{2,3})\s*marks\s*\]", txt, re.I)
        if m and P.pno == 0:
            return int(m.group(1))
    return None


def per_question_default(D: Doc):
    for P in D.pages[:2]:
        txt = norm(" ".join(l.text for l in P.lines))
        m = re.search(r"maximum mark for each question is\s*(\d{1,2})", txt, re.I)
        if m:
            return int(m.group(1))
    return None


def option_title(D: Doc, c: Cand, heads):
    """Short option heading (e.g. 'Sets, Relations and Groups') just above a question start."""
    best = option_line(D, c)
    if best is None:
        return None
    t = best.text.strip().rstrip(".:")
    return t[0].upper() + t[1:] if t else None


def option_line(D: Doc, c: Cand):
    P = D.pages[c.page]
    best = None
    for l in P.lines:
        if l.kind != "text" or not (c.y0 - 75 < l.y0 < c.y0 - 4) or len(l.text) > 50:
            continue
        if l.x0 > c.x0 + 10 or l.text.startswith("("):
            continue
        words = [w for w in re.findall(r"[A-Za-z]+", l.text) if len(w) > 3]
        caps = sum(w[0].isupper() for w in words)
        if not (l.bold or (words and caps >= 0.6 * len(words))):
            continue
        t = l.text.lower()
        if any(w in t for w in OPTION_WORDS) and not re.search(r"\d|answer|question|\[", t):
            if best is None or l.y0 > best.y0:
                best = l
    return best


# ----------------------------------------------------------------------------- main entry

def _qtype(exam, section, marks):
    if exam.get("paper") == "3":
        return "long"
    if section == "B":
        return "long"
    if marks is not None and marks >= 10:
        return "long"
    return "short"


def segment(exam: dict, out_dir: Path, overrides: dict | None) -> dict:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    ov = overrides or {}
    ov_q = {str(q["num"]): q for q in ov.get("questions", []) if "num" in q}
    drop = {str(x) for x in ov.get("drop", [])}
    mcq_ov = {str(k): v for k, v in (ov.get("mcq_answers") or {}).items()}
    skip_pages = int((ov.get("ms_offsets") or {}).get("skip_pages") or 0)

    result = {k: exam[k] for k in exam}
    notes = []
    D = Doc(exam["qp_pdf"])
    mark_foreign_pages(D, exam.get("paper"))
    result["qp_pages"] = len(D.pages)

    heads = section_heads(D)
    cands = find_candidates(D, ms_mode=False)
    chain = best_chain(cands, heads, allow_gap=True)
    if D.ocr:
        notes.append("question paper OCR'd (scan)")

    # the crop must include the question numbers (scans: they may be left of the text column)
    if chain:
        D.xL = max(0.0, min(D.xL, min(c.x0 for _, c, _ in chain) - 10))
    # ---- question starts
    qs = []
    for label, c, gap in chain:
        qs.append({"num": label, "cand": c, "gap": gap, "start": (c.page, start_cut(D, c))})
    # numbering sanity
    gaps = [q["num"] for q in qs if q["gap"]]
    if gaps:
        notes.append("numbering gaps before q" + ",".join(gaps))

    stops = [(p, y - 3) for p, y, _, _ in heads]
    # option headings ("Sets, Relations and Groups") sit just above a question number
    for q in qs:
        ol = option_line(D, q["cand"])
        if ol is not None:
            stops.append((ol.page, ol.y0 - 3))
    # also stop at an option heading that precedes a question (handled through start cut) and at
    # the start of the next question; build regions
    regions = build_regions(D, [q["start"] for q in qs], stops)
    for q, reg in zip(qs, regions):
        q["pieces"] = reg

    # ---- overrides: explicit qp regions (may also add questions that were not detected)
    for num, o in ov_q.items():
        if "qp" not in o:
            continue
        pcs = [(int(p), float(a), float(b)) for p, a, b in o["qp"]]
        ex = [q for q in qs if q["num"] == num]
        if ex:
            ex[0]["pieces"] = pcs
            ex[0]["override"] = True
        else:
            qs.append({"num": num, "cand": None, "gap": False, "start": (pcs[0][0], pcs[0][1]),
                       "pieces": pcs, "override": True})
    qs.sort(key=lambda q: q["start"])
    qs = [q for q in qs if q["num"] not in drop]

    # ---- markscheme
    M = None
    ms_map = {}
    if exam.get("ms_pdf"):
        try:
            M = Doc(exam["ms_pdf"], is_ms=True)
            mark_foreign_pages(M, exam.get("paper"))
        except Exception as e:  # pragma: no cover
            notes.append(f"markscheme unreadable: {e}")
            M = None
    if M is not None:
        try:
            if M.ocr:
                notes.append("markscheme OCR'd (scan)")
            fm = fm_end_pos(M)
            if skip_pages:
                fm = max(fm, (skip_pages, 0.0))
            mheads = section_heads(M)
            mcands = find_candidates(M, ms_mode=True, fm_end=fm)
            expected = [q["num"] for q in qs]
            mchain = best_chain(mcands, mheads, allow_gap=True, expected=expected)
            if mchain:
                M.xL = max(0.0, min(M.xL, min(c.x0 for _, c, _ in mchain) - 10))
            mstarts = [(c.page, start_cut(M, c)) for _, c, _ in mchain]
            mstops = [(p, y - 3) for p, y, _, _ in mheads if (p, y) > fm]
            mregs = build_regions(M, mstarts, mstops, stop_at_cut=False)
            for k, ((label, c, g), reg) in enumerate(zip(mchain, mregs)):
                # a gap after this heading means its crop also holds the missing question(s)
                absorbs = k + 1 < len(mchain) and mchain[k + 1][2]
                if label not in ms_map:
                    ms_map[label] = {"pieces": reg, "gap": False, "absorbs": absorbs}
            # the last heading found also holds any missing questions after it
            found = [lab for lab, _, _ in mchain]
            if found and expected and found[-1] in expected and found[-1] != expected[-1] \
                    and expected.index(found[-1]) < len(expected) - 1 and found[-1] in ms_map:
                ms_map[found[-1]]["absorbs"] = True
            # first question's heading lost (OCR): it runs from the end of the front matter to the
            # second question's heading
            if mchain and expected and expected[0] not in ms_map and len(expected) > 1 \
                    and mchain[0][0] == expected[1]:
                c2 = mchain[0][1]
                sp, sy = fm if fm > (0, 0.0) else (0, 0.0)
                while sp < c2.page and _is_cover(M.pages[sp]):
                    sp, sy = sp + 1, 0.0
                if c2.page - sp <= 3:
                    reg = build_regions(M, [(sp, max(sy, M.pages[sp].body_top))], [], stop_at_cut=False)[0]
                    reg = [(p_, a, min(b, mstarts[0][1]) if p_ == c2.page else b) for p_, a, b in reg
                           if (p_, a) < (c2.page, mstarts[0][1])]
                    if reg:
                        ms_map[expected[0]] = {"pieces": reg, "gap": False, "absorbs": True}
                        notes.append(f"markscheme: q{expected[0]} heading not found, crop guessed")
            missing = [n for n in expected if n not in ms_map and not (n in ov_q and "ms" in ov_q[n])]
            if missing:
                notes.append("markscheme: no heading found for q" + ",".join(missing))
            extra = [n for n in ms_map if n not in expected]
            if extra:
                notes.append("markscheme headings without question: " + ",".join(extra))
        except Exception as e:  # never lose the question paper because of a markscheme problem
            notes.append(f"markscheme segmentation failed: {type(e).__name__}: {e}")
            ms_map = {}

    for num, o in ov_q.items():
        if "ms" in o and M is not None:
            ms_map[num] = {"pieces": [(int(p), float(a), float(b)) for p, a, b in o["ms"]], "gap": False,
                           "override": True}

    # ---- render
    eid = exam["exam_id"]
    per_q = per_question_default(D)
    questions = []
    total_marks = 0
    any_uncertain = False
    for q in qs:
        num = q["num"]
        safe = re.sub(r"[^A-Za-z0-9]+", "_", num)
        flags = []
        im, kept = render_region(D, q["pieces"])
        img_name = None
        text = ""
        if im is not None:
            img_name = f"q{safe}.webp"
            save_webp(im, out_dir / img_name)
            text = region_text(D, kept)
            if diagram_share(D, kept) > 0.22:
                flags.append("diagram-heavy")
        else:
            flags.append("crop-uncertain")
        if q.get("gap") and not q.get("override"):
            flags.append("crop-uncertain")
        npages = len({p for p, _, _ in kept})
        if npages > 5 and not q.get("override"):
            flags.append("crop-uncertain")
        # a question whose region swallowed the next number (missed start) is long; check text
        if D.ocr:
            flags.append("text-ocr")
        c = q["cand"]
        section = None
        if c is not None:
            section = section_of(c.pos, heads)
        else:
            section = section_of(q["start"], heads)
        # combined paper 3 (2006/07): section letters are options, not short/long sections
        is_combined = bool(re.match(r"^[A-E]\d+$", num))
        opt = None
        if c is not None and (is_combined or (exam.get("paper") == "2" and section == "B")):
            opt = option_title(D, c, heads)
        if is_combined:
            section = None
        marks = parse_marks(text, None)
        if per_q is not None and not MAXMARK_RE.search(text):
            marks = per_q
        # markscheme
        ms_name, ms_text, status = None, None, "missing"
        msr = ms_map.get(num)
        if msr is not None and M is not None:
            mim, mkept = render_region(M, msr["pieces"])
            if mim is not None:
                ms_name = f"q{safe}_ms.webp"
                save_webp(mim, out_dir / ms_name)
                ms_text = region_text(M, mkept) or None
                status = "ok"
                if marks is None and not M.ocr:
                    mt = ms_total(ms_text or "")
                    if mt is not None and 1 <= mt <= 40:
                        marks = mt
                        flags.append("marks-from-ms")
                cons = ms_consistent(ms_text or "", marks)
                if cons is False and not msr.get("override") and not (M.ocr or D.ocr):
                    # totals disagree: either our crop or the extraction is off
                    status = "suspect"
                if msr.get("absorbs") and status == "ok":
                    status = "suspect"
        if marks is not None:
            total_marks += marks
        if "crop-uncertain" in flags:
            any_uncertain = True
        qd = {
            "id": f"{eid}-q{safe}",
            "num": num,
            "section": section,
            "marks": marks,
            "qtype": _qtype(exam, section, marks),
            "image": img_name,
            "ms_image": ms_name,
            "text": text,
            "ms_text": ms_text,
            "mcq_answer": mcq_ov.get(num),
            "topics": [],
            "subtopics": [],
            "answer_status": status if not mcq_ov.get(num) else "ok",
            "flags": sorted(set(flags)),
        }
        if opt:
            qd["option"] = opt
        questions.append(qd)

    # pre-2008 paper 1: every question carries the same mark, but 2003-07 papers do not print it;
    # take the value most questions agree on (printed or from the markscheme annotations)
    if exam.get("paper") == "1" and int(exam.get("year", 0)) < 2008 and len(questions) >= 15 \
            and per_q is None and not any(MAXMARK_RE.search(q["text"] or "") for q in questions):
        est = [v for v in (ms_mark_estimate(q["ms_text"]) for q in questions) if v]
        known = [q["marks"] for q in questions if q["marks"] is not None and "marks-from-ms" in q["flags"]]
        pool = est or known
        if pool:
            mode = max(set(pool), key=pool.count)
            if pool.count(mode) >= 0.5 * len(pool) and 2 <= mode <= 10:
                for q in questions:
                    if q["marks"] != mode:
                        total_marks += mode - (q["marks"] or 0)
                        q["marks"] = mode
                    q["flags"] = sorted(set(q["flags"] + ["marks-from-ms"]))
                notes.append(f"marks not printed; assumed {mode} per question (modal markscheme value)")
    # combined paper 3: the option heading only precedes the first question of each section
    cur = {}
    for qd in questions:
        m = re.match(r"^([A-E])\d+$", qd["num"])
        if not m:
            continue
        if qd.get("option"):
            cur[m.group(1)] = qd["option"]
        elif m.group(1) in cur:
            qd["option"] = cur[m.group(1)]
    pt = paper_total(D)
    year, paper = int(exam.get("year", 0)), exam.get("paper")
    mismatch = False
    combined = any(re.match(r"^[A-E]\d", q["num"]) for q in questions)
    if combined:
        # 2006/07 combined paper 3: every option section is worth 60
        secs = {}
        for q in questions:
            secs[q["num"][0]] = secs.get(q["num"][0], 0) + (q["marks"] or 0)
        bad = {k: v for k, v in secs.items() if v != 60}
        if bad:
            mismatch = True
            notes.append("option section mark sums != 60: " + ", ".join(f"{k}={v}" for k, v in sorted(bad.items())))
        else:
            notes.append("each option section sums to 60")
    else:
        # papers with optional Section B questions (answer ONE): total = A + one B
        secB = [q["marks"] for q in questions if q["section"] == "B" and q["marks"]]
        if paper == "2" and year < 2006 and len(set(secB)) == 1:
            total_marks = sum(q["marks"] or 0 for q in questions if q["section"] != "B") + secB[0]
        exp, src = pt, "paper total"
        if exp is None and exam.get("syllabus") == "math-hl-legacy":
            src = "expected total"
            if paper in ("1", "2") and 2008 <= year <= 2018:
                exp = 120
            elif paper == "2" and 2006 <= year <= 2007:
                exp = 120
            elif paper == "3" and 2008 <= year <= 2018:
                exp = 60
            elif paper == "2" and 2000 <= year <= 2005:
                exp = 100
        if exp is not None and total_marks:
            if exp != total_marks:
                mismatch = True
                notes.append(f"sum of question marks {total_marks} != {src} {exp}")
            else:
                notes.append(f"marks sum matches {src} {exp}")
    result["questions"] = questions
    ms_bad = M is not None and any(q["answer_status"] != "ok" for q in questions)
    if not questions:
        result["status"] = "failed"
    elif any_uncertain or gaps or mismatch or ms_bad or any(q["image"] is None for q in questions):
        result["status"] = "partial"
    else:
        result["status"] = "done"
    prev = exam.get("notes") or ""
    result["notes"] = "; ".join(x for x in [prev] + notes if x)
    return result


# ----------------------------------------------------------------------------- debugging CLI

if __name__ == "__main__":
    cat = {e["exam_id"]: e for e in json.loads((ROOT / "db" / "catalog.json").read_text())}
    eid = sys.argv[1]
    which = sys.argv[2] if len(sys.argv) > 2 else "qp"
    e = cat[eid]
    D = Doc(e["qp_pdf"] if which == "qp" else e["ms_pdf"], is_ms=(which == "ms"))
    print("xrange", round(D.xL), round(D.xR), "ocr", D.ocr)
    heads = section_heads(D)
    print("heads", [(p, round(y), s) for p, y, s, _ in heads])
    fm = fm_end_pos(D) if which == "ms" else (0, 0)
    print("fm_end", fm)
    cands = find_candidates(D, which == "ms", fm)
    print("col", getattr(D, "numcol", None))
    for c in cands:
        print("  ", c, c.line.text[:50])
    ch = best_chain(cands, heads, allow_gap=True)
    print("chain", [(l, c.page, round(c.y0), g) for l, c, g in ch])
