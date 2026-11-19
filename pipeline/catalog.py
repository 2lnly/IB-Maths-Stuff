#!/usr/bin/env python3
"""Build db/catalog.json: one record per (English) exam paper, paired with its markscheme.

Subjects:
  math      Mathematics HL (legacy, -> Nov 2020) + Mathematics: analysis and approaches HL (2021+)
  physics   Physics HL
  economics Economics SL (HL/SL combined papers count, level "HLSL")

Pipeline
  1. collect candidate PDFs from both source trees (read-only)
  2. extract metadata per PDF with PyMuPDF (first pages text; OCR fallback via tesseract for scans),
     cached in .scratch/catalog/meta_cache.json keyed by (path, size, mtime)
  3. identify each PDF: the IB paper code printed on every page
     (e.g. "M15/5/MATHL/HP1/ENG/TZ1/XX/M") is the primary truth; cover text and path are fallbacks
  4. group into exams, pick the best question paper / markscheme copy, write catalog.json

Usage: python3 pipeline/catalog.py [--no-cache] [--extract-only]
Side outputs (scratch): .scratch/catalog/skipped.json lists every candidate PDF not used and why.
"""
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor

import fitz  # PyMuPDF

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_YEAR = os.path.expanduser('~/stuff/IB PAST PAPERS - YEAR')
SRC_MATH = os.path.expanduser('~/stuff/Math AA HL')
SCRATCH = os.path.join(ROOT, '.scratch', 'catalog')
CACHE = os.path.join(SCRATCH, 'meta_cache.json')
OUT = os.path.join(ROOT, 'db', 'catalog.json')

# --------------------------------------------------------------------------------------------
# 1. candidates
# --------------------------------------------------------------------------------------------

SUBJ_NAME_RE = re.compile(r'(?i)math|physic|econ|aahl|aasl')
# directories in Math AA HL tree that hold derived PNG question crops, not source papers
SKIP_DIRS = {'all', 'newer', 'older', 'practice_topics', 'simplfied'}


def collect_candidates():
    out = []
    for dirpath, dirnames, filenames in os.walk(SRC_MATH):
        rel = os.path.relpath(dirpath, SRC_MATH)
        if rel.split(os.sep)[0] in SKIP_DIRS:
            dirnames[:] = []
            continue
        for f in filenames:
            if f.lower().endswith('.pdf'):
                out.append(os.path.join(dirpath, f))
    for dirpath, dirnames, filenames in os.walk(SRC_YEAR):
        rel = os.path.relpath(dirpath, SRC_YEAR)
        top = rel.split(os.sep)[0]
        if top == 'Computer Science HL':
            dirnames[:] = []
            continue
        for f in filenames:
            full = os.path.join(dirpath, f)
            if not f.lower().endswith('.pdf'):
                continue
            if top in ('Math AA', 'Physics HL', 'Economics SL') or SUBJ_NAME_RE.search(rel + '/' + f):
                out.append(full)
    return sorted(set(out))


# --------------------------------------------------------------------------------------------
# 2. metadata extraction
# --------------------------------------------------------------------------------------------

CODE_RE = re.compile(
    r'([MN])\s?(\d{2})\s?/\s?(\d)\s?/\s?([A-Z]{4,6})\s?/\s?([A-Z0-9]{2,5})\s?/\s?([A-Z]{3})\s?/\s?'
    r'(TZ\s?\d|T\s?Z\s?\d)(?:\s?/\s?([A-Z0-9]{2}))?(\s?/\s?M\+?)?', re.I)
META_VERSION = 2
NPAGES = 4


def ocr_pages(path, pages):
    texts = []
    with tempfile.TemporaryDirectory(dir=SCRATCH) as td:
        for p in pages:
            base = os.path.join(td, f'p{p}')
            subprocess.run(['pdftoppm', '-f', str(p + 1), '-l', str(p + 1), '-r', '200', '-gray',
                            '-png', '-singlefile', path, base], capture_output=True)
            png = base + '.png'
            if not os.path.exists(png):
                texts.append('')
                continue
            r = subprocess.run(['tesseract', png, '-', '--psm', '3'], capture_output=True, text=True)
            texts.append(r.stdout)
    return texts


def is_copyright_page(t):
    return ('No part of this product may be reproduced' in t or 'All rights reserved' in t) and \
        not re.search(r'Paper\s+\d', t) and len(t) > 600


def extract_one(path, old=None):
    """Return raw per-PDF metadata: page count + text of the first NPAGES pages (OCR if scanned)."""
    st = os.stat(path)
    rec = {'v': META_VERSION, 'path': path, 'size': st.st_size, 'mtime': int(st.st_mtime),
           'pages': 0, 'ptext': [], 'ocr': False, 'error': None}
    try:
        doc = fitz.open(path)
    except Exception as e:  # noqa
        rec['error'] = f'open: {e}'
        return rec
    rec['pages'] = doc.page_count
    texts = []
    for i in range(min(NPAGES, doc.page_count)):
        try:
            texts.append(doc[i].get_text())
        except Exception:
            texts.append('')
    doc.close()
    if len(re.sub(r'\s', '', ''.join(texts))) < 80:
        rec['ocr'] = True
        if old and old.get('ocr') and old.get('ptext'):
            texts = old['ptext']
        elif old and old.get('ocr') and old.get('text'):
            texts = [old['text']]
        else:
            texts = ocr_pages(path, list(range(min(3, rec['pages']))))
    rec['ptext'] = [t[:4000] for t in texts]
    return rec


def _extract_star(args):
    return extract_one(*args)


def load_meta(use_cache=True):
    os.makedirs(SCRATCH, exist_ok=True)
    cache = {}
    if os.path.exists(CACHE):
        with open(CACHE) as f:
            cache = {r['path']: r for r in json.load(f)}
    cands = collect_candidates()
    todo, out = [], []
    for p in cands:
        st = os.stat(p)
        r = cache.get(p)
        fresh = r and r['size'] == st.st_size and r['mtime'] == int(st.st_mtime)
        if use_cache and fresh and r.get('v') == META_VERSION:
            out.append(r)
        else:
            todo.append((p, r if fresh else None))
    if todo:
        print(f'extracting {len(todo)} PDFs ({len(out)} cached)', file=sys.stderr)
        with ProcessPoolExecutor(max_workers=min(44, os.cpu_count() or 4)) as ex:
            out.extend(ex.map(_extract_star, todo, chunksize=4))
        with open(CACHE, 'w') as f:
            json.dump(out, f)
    return out


# --------------------------------------------------------------------------------------------
# 3. identification
# --------------------------------------------------------------------------------------------

LANG_PATH_RE = re.compile(
    r'(?i)spanish|french|german|\[[a-z]+\]|espa[nñ]ol|fran[cç]ais|deutsch|chinese|japanese|'
    r'(?:^|[_\-\s.])(?:ES|FR|DE|SPA|FRE|GER)(?=[_\-\s.]|$)|-spa\b|-fre\b')
SUBJ_CODES = {
    'MATHL': ('math', 'legacy'), 'MATHX': ('math', 'aa'), 'MATHY': ('math-ai', None),
    'MATME': ('math-sl', None), 'MATSD': ('math-studies', None), 'FURMA': ('math-further', None),
    'PHYSI': ('physics', None), 'PHISI': ('physics', None), 'PHYSX': ('physics', None),
    'ECONO': ('economics', None), 'COMSC': ('cs', None),
}
MONTHS = {'january': 'May', 'february': 'May', 'march': 'May', 'april': 'May', 'may': 'May',
          'june': 'May', 'october': 'November', 'november': 'November', 'december': 'November'}
OPTION_NAMES = [
    ('Series and differential equations', re.compile(r'(?i)series\s*(and|&)\s*differential')),
    ('Statistics and probability', re.compile(r'(?i)statistics\s*(and|&)\s*probability')),
    ('Sets relations and groups', re.compile(r'(?i)sets,?\s*relations\s*(and|&)\s*groups')),
    ('Discrete mathematics', re.compile(r'(?i)discrete\s*mathematics')),
    ('Calculus', re.compile(r'(?i)calculus')),
]
PNUM_RE = re.compile(r'(?<![\d/])(22|88)(\d\d)\s?[–\-—]\s?(\d{4})(M?)(?!\d)')


def norm_tz(tz):
    if not tz:
        return None
    tz = tz.upper().replace(' ', '')
    return None if tz == 'TZ0' else tz


def parse_path(path):
    rel = path
    for base in (SRC_YEAR, SRC_MATH):
        if path.startswith(base):
            rel = os.path.relpath(path, base)
    fname = os.path.basename(path)
    parts = rel.split(os.sep)
    info = {'rel': rel, 'tree': 'math' if path.startswith(SRC_MATH) else 'year', 'top': parts[0]}
    info['lang_foreign'] = bool(LANG_PATH_RE.search(fname)) or any(
        LANG_PATH_RE.search(p) for p in parts[:-1])
    low = fname.lower()
    info['ms'] = 'markscheme' in low or 'mark_scheme' in low or 'mark scheme' in low
    # year/session: filename first, then parent dirs from nearest
    year = session = None
    for comp in [fname] + parts[-2::-1]:
        m = re.search(r'(?<!\d)((?:19|20)\d\d)[_ ]+(May|November)', comp) or \
            re.search(r'(May|November)[_ ]+((?:19|20)\d\d)(?!\d)', comp)
        if m:
            g = m.groups()
            year, session = (int(g[0]), g[1]) if g[0][0].isdigit() else (int(g[1]), g[0])
            break
        m = re.search(r'(?<![A-Za-z])([MN])(\d\d)(?![\d])', comp)
        if m and not re.search(r'(?i)paper', comp[:m.start()][-6:]):
            year, session = 2000 + int(m.group(2)), 'May' if m.group(1) == 'M' else 'November'
            break
    if year is None:
        for comp in [fname] + parts[-2::-1]:
            m = re.search(r'(?<!\d)((?:19|20)\d\d)(?!\d)', comp)
            if m:
                year = int(m.group(1))
                break
    if re.search(r'(?i)nov(?:ember)?(?=\.pdf$|_|$)|HLnov', fname) and session is None:
        session = 'November'
    elif re.search(r'(?i)(markscheme|HL)nov\.pdf$', fname):
        session = 'November'
    info['year'], info['session'] = year, session
    m = re.search(r'(?i)TZ\s?([0-3])', fname) or re.search(r'(?i)TZ\s?([0-3])', parts[-2] if len(parts) > 1 else '')
    info['tz'] = norm_tz('TZ' + m.group(1)) if m else None
    m = re.search(r'(?i)(?:zone\s?|TZ)([ABC](?:&[ABC])?)(?=[\s_.]|$)', fname)
    info['zone'] = m.group(1).upper() if m else None
    m = re.search(r'(?i)paper[_ ]*(1A|1B|[123])', fname) or re.search(r'(?i)\bP(1A|1B|[123])\b', fname.replace('_', ' ')) \
        or re.search(r'(?i)-P(1A|1B|[123])\.', fname)
    info['paper'] = m.group(1).upper() if m else None
    if re.search(r'(?i)HLSL|SLHL', fname):
        info['level'] = 'HLSL'
    elif re.search(r'(?i)(?:^|[_\s\-])HL(?=[_\s\-.]|nov|$)|AAHL|AIHL', fname):
        info['level'] = 'HL'
    elif re.search(r'(?i)(?:^|[_\s\-])SL(?=[_\s\-.]|$)|AASL|AISL', fname):
        info['level'] = 'SL'
    else:
        info['level'] = None
    lowrel = rel.lower()
    if 'applications' in low or re.search(r'(?i)\bAI|AIHL|AISL|Math AI', fname + ' ' + parts[-2] if len(parts) > 1 else fname):
        subj = 'math-ai'
    elif 'studies' in low:
        subj = 'math-studies'
    elif 'further' in low:
        subj = 'math-further'
    elif re.search(r'(?i)physic', fname):
        subj = 'physics'
    elif re.search(r'(?i)econ', fname):
        subj = 'economics'
    elif re.search(r'(?i)math|aahl|aasl', fname):
        subj = 'math'
    elif 'physics' in lowrel:
        subj = 'physics'
    elif 'econ' in lowrel:
        subj = 'economics'
    else:
        subj = None
    info['subject'] = subj
    info['aa'] = bool(re.search(r'(?i)analysis|_AA_|AAHL|AASL|Math AA|Maths-AA', fname))
    m = None
    for name, rx in OPTION_NAMES:
        if rx.search(fname.replace('_', ' ')):
            m = name
            break
    info['option'] = m
    # donated / student-supplied copies: DONATED folders, zone-named files, "2023__..." copies
    info['donated'] = 'DONATED' in rel or info['zone'] is not None or bool(re.match(r'\d{4}__', fname))
    return info


def cover_text(rec):
    pages = [t for t in rec['ptext'] if not is_copyright_page(t)]
    return '\n'.join(pages)


def parse_text(rec):
    t = cover_text(rec)
    flat = re.sub(r'[ \t ]+', ' ', t)
    flat1 = re.sub(r'\s+', ' ', t)
    info = {'code': None}
    m = CODE_RE.search(t)
    if m:
        tz = re.sub(r'(?i)\s|T\s?Z', '', m.group(7))
        info['code'] = {
            'session': 'May' if m.group(1).upper() == 'M' else 'November',
            'year': 2000 + int(m.group(2)) if int(m.group(2)) < 80 else 1900 + int(m.group(2)),
            'subj': m.group(4).upper(), 'comp': m.group(5).upper(), 'lang': m.group(6).upper(),
            'tz': norm_tz('TZ' + tz), 'xx': (m.group(8) or '').upper(), 'ms': bool(m.group(9)),
            'raw': re.sub(r'\s', '', m.group(0)).upper()}
    pn = [(a, b, c, d) for a, b, c, d in PNUM_RE.findall(flat1)]
    info['pnum'] = None
    if pn:
        a, b, c, d = pn[0]
        info['pnum'] = f'{a}{b}-{c}'
        info['pnum_ms'] = bool(d)
    head = flat1[:2500]
    info['ms'] = bool(re.search(r'(?i)\bmark\s?scheme\b', head[:600])) or \
        bool(re.search(r'(?i)^\W*(\d+ pages )?mark\s?scheme', head)) or \
        (info['code'] or {}).get('ms', False) or info.get('pnum_ms', False)
    # subject line
    hl = head.lower()
    # the title is the earliest subject phrase on the cover (later mentions such as
    # "mathematics HL and further mathematics HL formula booklet" must not win)
    cands = []
    for rx, s in [(r'mathematics\s*:?\s*analysis\s+and\s+approaches', 'math-aa'),
                  (r'mathematics\s*:?\s*applications\s+and\s+interpretation', 'math-ai'),
                  (r'mathematical studies', 'math-studies'), (r'further mathematics', 'math-further'),
                  (r'computer science', 'cs'),
                  (r'\bphysics\b', 'physics'), (r'\beconomics\b', 'economics'), (r'\bmathematics\b', 'math')]:
        mm = re.search(rx, hl)
        if mm:
            cands.append((mm.start(), -(mm.end() - mm.start()), s))
    info['subject'] = min(cands)[2] if cands else None
    lv = re.search(r'(?i)(higher|standard)\s+level(\s+and\s+(higher|standard)\s+level)?|physics\s+higher\b', head)
    if lv:
        if lv.group(2):
            info['level'] = 'HLSL'
        else:
            info['level'] = 'HL' if lv.group(0).lower().startswith(('higher', 'physics')) else 'SL'
    else:
        info['level'] = None
    head_nb = re.sub(r'\[[^\]]{0,40}\]', ' ', head)  # drop e.g. "[Paper 1A and Paper 1B]"
    pm = re.search(r'(?i)\bpaper\s+(1A|1B|[123])\b', head_nb)
    info['paper'] = pm.group(1).upper() if pm else None
    opt = None
    if info['paper'] == '3' or re.search(r'(?i)paper\s+3', head):
        seg = head_nb[pm.start(): pm.start() + 200] if pm else head
        for name, rx in OPTION_NAMES:
            if rx.search(seg):
                opt = name
                break
    info['option'] = opt
    dm = re.search(r'(?i)\b(\d{1,2})\s+(january|february|march|april|may|june|october|november|december)\s+((?:19|20)\d\d)\b', head) \
        or re.search(r'(?i)\b(january|february|march|april|may|june|october|november|december)\s+(\d{1,2}),?\s+((?:19|20)\d\d)\b', head)
    sm = re.search(r'(?i)mark\s?scheme\s+(may|november)\s+((?:19|20)\d\d)', head)
    if sm:
        info['year'], info['session'] = int(sm.group(2)), sm.group(1).capitalize()
    elif dm:
        g = dm.groups()
        mon = g[1] if g[0].isdigit() else g[0]
        info['year'], info['session'] = int(g[2]), MONTHS[mon.lower()]
    else:
        sm = re.search(r'(?i)\b(may|november)\s+((?:19|20)\d\d)\b', head)
        info['year'], info['session'] = (int(sm.group(2)), sm.group(1).capitalize()) if sm else (None, None)
    if info['pnum']:
        pses = 'May' if info['pnum'][:2] == '22' else 'November'
        pyear = 2000 + int(info['pnum'][2:4])
        info['pnum_session'] = (pyear, pses)
        if info['year'] is None or (rec['ocr'] and (info['year'], info['session']) != (pyear, pses)):
            info['year'], info['session'] = pyear, pses
    info['zones'] = bool(re.search(r'(?i)zone\s?a', head))
    info['answer_one'] = bool(re.search(r'(?i)answer\s+one\s+question', flat1))
    info['sections'] = bool(re.search(r'(?i)section\s+A\b', flat1[:3000]))
    return info


FOREIGN_TEXT_RE = re.compile(r'(?i)nivel superior|niveau sup[ée]rieur|nivel medio|niveau moyen|'
                             r'esquema de calificaci|bar[eè]me de notation|prueba \d|[ée]preuve \d|'
                             r'h[öo]heres niveau|leistungsstufe|grundstufe|markierungsschema')
XX_OPTIONS = {'SE': 'Series and differential equations', 'ST': 'Statistics and probability',
              'SG': 'Sets relations and groups', 'DM': 'Discrete mathematics', 'CA': 'Calculus',
              'SP': 'Statistics and probability'}
SUBJ_KEEP = {'math', 'physics', 'economics'}


def resolve(rec):
    """Combine code / cover text / path evidence into one identity. Returns (doc, skip_reason)."""
    p = parse_path(rec['path'])
    t = parse_text(rec) if rec['ptext'] else {'code': None, 'pnum': None, 'ms': False, 'subject': None,
                                             'level': None, 'paper': None, 'option': None,
                                             'year': None, 'session': None, 'zones': False,
                                             'answer_one': False}
    code = t['code']
    notes = []
    d = {'path': rec['path'], 'pages': rec['pages'], 'ocr': rec['ocr'], 'size': rec['size'],
         'donated': p['donated'], 'pnum': t['pnum'], 'tree': p['tree'], 'top': p['top'],
         'zone': p['zone'], 'text_ok': bool(code or t['subject']), 'answer_one': t['answer_one'], 'sections': t.get('sections', False)}
    if rec['error']:
        return d, 'unreadable: ' + rec['error']
    head = cover_text(rec)[:3000]
    # language
    if code and code['lang'] != 'ENG':
        return d, f"non-English (code {code['raw']})"
    if p['lang_foreign']:
        return d, 'non-English (filename)'
    if FOREIGN_TEXT_RE.search(head) and not re.search(r'(?i)higher level|standard level|markscheme', head):
        return d, 'non-English (cover text)'
    # subject
    subj = syl = None
    if code and code['subj'] in SUBJ_CODES:
        subj, flav = SUBJ_CODES[code['subj']]
        if subj == 'math':
            syl = 'math-aa-hl' if flav == 'aa' else 'math-hl-legacy'
    elif t['subject']:
        subj = t['subject']
        if subj == 'math-aa':
            subj, syl = 'math', 'math-aa-hl'
        elif subj == 'math':
            syl = 'math-hl-legacy'
    else:
        subj = p['subject']
        if subj == 'math':
            syl = 'math-aa-hl' if p['aa'] else 'math-hl-legacy'
        if subj:
            notes.append('identity from filename only (no readable cover)')
    if t['subject'] and p['subject'] and t['subject'].split('-')[0] != p['subject'].split('-')[0] \
            and not (t['subject'] == 'math-aa' and p['subject'] == 'math'):
        notes.append(f"filename suggests {p['subject']} but cover says {t['subject']}")
    if subj == 'math' and syl == 'math-hl-legacy' and p['aa'] and not code:
        notes.append('filename says analysis and approaches but cover says Mathematics')
    if subj not in SUBJ_KEEP:
        return d, f'other subject ({subj})'
    # level
    lvl = None
    if code:
        lvl = {'H': 'HL', 'S': 'SL', 'B': 'HLSL'}.get(code['comp'][0])
    lvl = lvl or t['level'] or p['level']
    if t['level'] and p['level'] and t['level'] != p['level'] and not code:
        if p['level'] == 'HLSL':
            lvl = 'HLSL'
        else:
            notes.append(f"filename level {p['level']} but cover says {t['level']}")
    want = {'math': {'HL'}, 'physics': {'HL'}, 'economics': {'SL', 'HLSL'}}[subj]
    if lvl not in want:
        return d, f'{subj} level {lvl}'
    # paper
    paper = None
    if code:
        cm = re.match(r'[HSB]P(M|\d)', code['comp'])
        paper = ('1' if cm.group(1) == 'M' else cm.group(1)) if cm else None
    paper = paper or t['paper'] or p['paper']
    if p['paper'] in ('1A', '1B') and paper == '1':
        paper = p['paper']
    if t['paper'] and p['paper'] and t['paper'] != p['paper'] and not (
            p['paper'] in ('1A', '1B') and t['paper'] == '1'):
        notes.append(f"filename paper {p['paper']} but cover says {t['paper']}")
    if not paper:
        return d, 'paper number undetermined'
    # session
    year, session = (code['year'], code['session']) if code else (t['year'], t['session'])
    if year is None:
        year, session = p['year'], p['session'] or session
        notes.append('session from path only')
    elif session is None:
        session = p['session']
    if p['year'] and (p['year'], p['session']) != (year, session) and p['session']:
        notes.append(f"path says {p['session']} {p['year']}, paper says {session} {year}")
    if not year or not session:
        return d, f'session undetermined ({year} {session})'
    # time zone
    if code:
        tz = code['tz']
        if p['tz'] != tz and (p['tz'] or tz):
            notes.append(f"filename TZ {p['tz']} but printed code says {tz}")
    else:
        tz = p['tz']
    # option (legacy math paper 3)
    option = None
    if subj == 'math' and syl == 'math-hl-legacy' and paper == '3':
        # cover text first: code suffix SE was kept when "Series and differential equations"
        # was renamed "Calculus" (first exams 2014)
        option = t['option']
        if not option and code and code['xx'] in XX_OPTIONS:
            option = XX_OPTIONS[code['xx']]
            if code['xx'] == 'SE' and year >= 2014:
                option = 'Calculus'
        option = option or p['option']
        if p['option'] and option and p['option'] != option:
            notes.append(f"filename option {p['option']} but cover says {option}")
    ms = t['ms'] if rec['ptext'] and (code or t['subject']) else p['ms']
    if ms != p['ms']:
        notes.append(f"filename {'is' if p['ms'] else 'is not'} markscheme but cover says otherwise")
    # syllabus
    if subj == 'physics':
        syl = 'physics-2023' if (paper in ('1A', '1B') or (year, session) >= (2025, 'May')) else 'physics-legacy'
        if year >= 2025 and paper not in ('1A', '1B', '2'):
            notes.append('post-2025 physics paper that is not 1A/1B/2')
    elif subj == 'economics':
        syl = 'econ-2020' if year >= 2022 else 'econ-legacy'
    if subj == 'math' and syl == 'math-aa-hl' and year < 2021:
        notes.append('analysis and approaches cover before 2021')
    d.update({'subject': subj, 'syllabus': syl, 'year': year, 'session': session, 'tz': tz,
              'paper': paper, 'option': option, 'level': lvl, 'ms': ms, 'notes': notes,
              'code': code['raw'] if code else None})
    return d, None


# --------------------------------------------------------------------------------------------
# 4. grouping, dedupe, pairing
# --------------------------------------------------------------------------------------------

WORD_RE = re.compile(r'[a-z]{5,}')


def words(rec):
    return set(WORD_RE.findall(cover_text(rec).lower()))


DEEP_CACHE = os.path.join(SCRATCH, 'deep_ocr.json')
_deep = None


def deep_words(d, max_pages=8):
    """Words of the first max_pages pages (OCR for scans, cached) - used to match donated scans."""
    global _deep
    if _deep is None:
        _deep = json.load(open(DEEP_CACHE)) if os.path.exists(DEEP_CACHE) else {}
    key = f"{d['path']}|{d['size']}"
    if key not in _deep:
        if d['ocr']:
            doc = fitz.open(d['path'])
            n = min(max_pages, doc.page_count)
            doc.close()
            txt = '\n'.join(ocr_pages(d['path'], list(range(n))))
        else:
            doc = fitz.open(d['path'])
            txt = '\n'.join(doc[i].get_text() for i in range(min(max_pages + 2, doc.page_count)))
            doc.close()
        _deep[key] = txt
        with open(DEEP_CACHE, 'w') as f:
            json.dump(_deep, f)
    return set(WORD_RE.findall(_deep[key].lower()))


def source_rank(d):
    """Higher is better: curated subject subtrees, then session trees, then donated copies."""
    if d['donated']:
        return 0
    if d['tree'] == 'year' and d['top'] in ('Math AA', 'Physics HL', 'Economics SL'):
        return 4
    if d['tree'] == 'math' and re.match(r'\d{4} (May|November) Examination Session', d['top']):
        return 4
    if d['tree'] == 'year':
        return 3
    return 2


def slug(s):
    return re.sub(r'[^a-z0-9]+', '-', s.lower()).strip('-')


def exam_id(e):
    eid = f"{e['subject']}-{e['year']}-{e['session'][0]}-P{e['paper']}"
    if e['option']:
        eid += '-' + slug(e['option'])
    if e['tz']:
        eid += '-' + e['tz']
    return eid


def build(metas):
    recs = {r['path']: r for r in metas}
    docs, skipped = [], []
    resolved = {r['path']: resolve(r) for r in metas}
    twins = defaultdict(list)
    for r in metas:
        twins[(r['size'], r['pages'])].append(r['path'])
    for r in metas:
        d, why = resolved[r['path']]
        if why and why.startswith(('session undetermined', 'paper number undetermined')):
            for other in twins[(r['size'], r['pages'])]:
                od, owhy = resolved[other]
                if other != r['path'] and not owhy:
                    d = dict(od, path=r['path'], donated=d['donated'], tree=d['tree'], top=d['top'],
                             zone=d['zone'], notes=od['notes'] + [f'identity copied from byte-identical {other}'])
                    why = None
                    break
        if why:
            skipped.append({'path': r['path'], 'reason': why})
            continue
        head = cover_text(r)
        if re.search(r'(?i)\bspecimen\b', head[:1500] + os.path.basename(r['path'])):
            skipped.append({'path': r['path'], 'reason': 'specimen paper'})
            continue
        if not d['ocr'] and not d['text_ok'] and d['donated']:
            skipped.append({'path': r['path'], 'reason': 'unofficial transcription (no IB cover/paper code)'})
            continue
        if not d['ms'] and d['pages'] <= 2 and d['subject'] != 'physics':
            if not re.search(r'(?i)\d+ pages', head[:800]) or d['pages'] <= 1:
                skipped.append({'path': r['path'], 'reason': f"fragment ({d['pages']} page(s))"})
                continue
        docs.append(d)

    # ---- pnum -> tz map from text-based (trustworthy) docs
    def base_key(d):
        return (d['subject'], d['year'], d['session'], d['paper'], d['option'])

    pnum_tz = {}
    for d in docs:
        if d['pnum'] and not d['ocr'] and not d['donated']:
            pnum_tz.setdefault((base_key(d), d['pnum']), set()).add(d['tz'])
    for (k, pn), tzs in pnum_tz.items():
        if len(tzs) > 1:
            print(f'WARNING paper number {pn} claimed by several time zones {tzs} for {k}', file=sys.stderr)
    for d in docs:
        if not (d['ocr'] or d['donated']):
            continue
        k = base_key(d)
        officials = [o for o in docs if base_key(o) == k and not o['ocr'] and not o['donated'] and not o['ms']]
        hit = pnum_tz.get((k, d['pnum'])) if d['pnum'] else None
        if hit and len(hit) == 1:
            tz = next(iter(hit))
            if tz != d['tz']:
                d['notes'].append(f"time zone {tz} assigned via printed paper number {d['pnum']}"
                                  + (f" (filename zone {d['zone']})" if d['zone'] else ''))
            d['tz'] = tz
            d['matched_official'] = True
        elif officials and not d['ms']:
            # no paper number read: compare cover/first-pages words with each official copy
            w = deep_words(d)
            ows = [deep_words(o) for o in officials]
            tzs = {o['tz'] for o in officials}
            indistinct = len(tzs) > 1 and len(set.union(*ows) - set.intersection(*ows)) < 20
            if len(tzs) == 1 or indistinct:
                # one official copy, or official TZ copies that are textually identical
                scored = sorted(((len(w & ow) / max(1, len(w)), -i) for i, ow in enumerate(ows)), reverse=True)
                scored = [(sc, -i) for sc, i in scored]
                best_s, second, ndist = scored[0][0], 0.0, len(w)
                ok = best_s >= 0.5
            else:
                # only words that distinguish the official copies (cover/instructions are shared)
                common = set.intersection(*ows)
                dist = w & (set.union(*ows) - common)
                ndist = len(dist)
                per_tz = defaultdict(float)
                for i, ow in enumerate(ows):
                    sc = len(dist & ow) / max(1, ndist)
                    per_tz[officials[i]['tz']] = max(per_tz[officials[i]['tz']], sc)
                scored = sorted(((sc, next(i for i, o in enumerate(officials) if o['tz'] == tz))
                                 for tz, sc in per_tz.items()), reverse=True)
                best_s = scored[0][0]
                second = scored[1][0] if len(scored) > 1 else 0.0
                ok = ndist >= 20 and best_s >= 0.6 and best_s - second >= 0.15
            best = officials[scored[0][1]]
            if ok:
                if best['tz'] != d['tz']:
                    d['notes'].append(f"time zone {best['tz']} assigned by distinctive-word overlap {best_s:.2f}"
                                      f" (next TZ {second:.2f}, {ndist} words) with {os.path.basename(best['path'])}")
                d['tz'] = best['tz']
                d['matched_official'] = True
            else:
                d['unmatched'] = f'best distinctive-word overlap {best_s:.2f}, next {second:.2f}, {ndist} words' + (f" (pnum {d['pnum']})" if d['pnum'] else '')

    groups = defaultdict(lambda: {'qp': [], 'ms': []})
    for d in docs:
        groups[base_key(d) + (d['tz'],)]['ms' if d['ms'] else 'qp'].append(d)

    exams = []
    for key, g in groups.items():
        subj, year, session, paper, option, tz = key
        if not g['qp']:
            for m in g['ms']:
                skipped.append({'path': m['path'], 'reason': 'markscheme without question paper'})
            continue
        # unmatched donated scans: keep only if there is no official paper at all for this slot
        qps = g['qp']
        unmatched = [q for q in qps if q.get('unmatched')]
        if unmatched:
            has_official = any(base_key(o) == key[:5] and not o['donated'] and not o['ocr']
                               for o in docs if not o['ms'])
            if has_official:
                for q in unmatched:
                    skipped.append({'path': q['path'], 'reason': 'donated scan not matched to any official '
                                    f"time-zone paper ({q['unmatched']}); official papers exist for this session"})
                qps = [q for q in qps if not q.get('unmatched')]
                if not qps:
                    continue

        def score(x, other_dirs):
            return (not x['ocr'], not x['donated'], os.path.dirname(x['path']) in other_dirs,
                    source_rank(x), -len(x['path']))
        ms_dirs = {os.path.dirname(m['path']) for m in g['ms']}
        qp = max(qps, key=lambda x: score(x, ms_dirs))
        # markscheme: prefer same directory as chosen qp; check printed paper number matches
        mss = g['ms']
        ms = max(mss, key=lambda x: score(x, {os.path.dirname(qp['path'])})) if mss else None
        notes = list(dict.fromkeys(qp['notes'] + (ms['notes'] if ms else [])))
        if ms and qp['pnum'] and ms['pnum'] and qp['pnum'] != ms['pnum']:
            good = [m for m in mss if m['pnum'] == qp['pnum']]
            if good:
                ms = max(good, key=lambda x: score(x, {os.path.dirname(qp['path'])}))
            else:
                notes.append(f"markscheme paper number {ms['pnum']} != question paper {qp['pnum']}")
        # duplicates
        alt = [q for q in qps if q is not qp]
        conflicts = []
        if alt:
            same = [q for q in alt if q['size'] == qp['size']]
            diff = [q for q in alt if q['size'] != qp['size']]
            qw = words(recs[qp['path']])
            for q in diff:
                why = []
                if q['pnum'] and qp['pnum']:
                    if q['pnum'] != qp['pnum']:
                        why.append(f"paper number {q['pnum']} vs {qp['pnum']}")
                else:
                    sim = len(qw & words(recs[q['path']])) / max(1, len(qw | words(recs[q['path']])))
                    if sim < 0.6 and not q['ocr']:
                        why.append(f'cover text similarity {sim:.2f}')
                if abs(q['pages'] - qp['pages']) > 2 and not q['ocr'] and not q['donated']:
                    why.append(f"{q['pages']} vs {qp['pages']} pages")
                if why:
                    conflicts.append(f"{q['path']} ({'; '.join(why)})")
            n_scan = sum(1 for q in alt if q['ocr'] or q['donated'])
            desc = f"{len(alt)} duplicate copies ({len(same)} byte-identical size"
            if n_scan:
                desc += f", {n_scan} donated/scanned"
            notes.append(desc + ')')
        for q in alt:
            for n in q['notes']:
                if 'assigned' in n:
                    notes.append(f"duplicate {q['path']}: {n}")
        if conflicts:
            notes.append('CONFLICTING COPIES kept aside: ' + ' | '.join(conflicts))
        if qp['ocr']:
            notes.append('question paper is a scan (no text layer)')
        if qp['donated']:
            notes.append('donated copy' + (f" (zone {qp['zone']})" if qp['zone'] else ''))
        if ms and ms['ocr']:
            notes.append('markscheme is a scan (no text layer)')
        if not ms:
            notes.append('no markscheme found')
        if qp['pnum']:
            notes.append(f"paper number {qp['pnum']}")
        if qp['code']:
            notes.append(f"code {qp['code']}")
        # syllabus sanity from structure
        syl = qp['syllabus']
        if subj == 'economics' and year >= 2013:  # 2010-2012 SL papers used yet another layout
            struct = None
            if paper == '1':
                struct = 'econ-legacy' if qp['sections'] else 'econ-2020'
            elif paper == '2':
                struct = 'econ-legacy' if qp['sections'] else 'econ-2020'
            if struct and struct != syl and not qp['ocr']:  # noqa
                notes.append(f'structure suggests {struct} but date rule gives {syl}')
        e = {'exam_id': None, 'subject': subj, 'syllabus': syl, 'year': year, 'session': session,
             'tz': tz, 'paper': paper, 'option': option, 'level': qp['level'],
             'qp_pdf': qp['path'], 'ms_pdf': ms['path'] if ms else None, 'notes': '; '.join(notes)}
        e['exam_id'] = exam_id(e)
        exams.append(e)
    # sibling time-zone papers that are textually identical apart from the paper number
    sib = defaultdict(list)
    for e in exams:
        sib[(e['subject'], e['year'], e['session'], e['paper'], e['option'])].append(e)
    for v in sib.values():
        if len(v) < 2:
            continue
        sig = {}
        for e in v:
            try:
                doc = fitz.open(e['qp_pdf'])
                txt = ''.join(p.get_text() for p in doc)
                doc.close()
            except Exception:
                continue
            txt = re.sub(r'\s+', '', PNUM_RE.sub('', CODE_RE.sub('', txt)))
            if len(txt) > 500:
                sig[e['exam_id']] = hashlib.md5(txt.encode()).hexdigest()
        for e in v:
            same = [o for o in sig if o != e['exam_id'] and sig.get(e['exam_id']) == sig[o]]
            if same:
                e['notes'] += ('; ' if e['notes'] else '') + \
                    f"question paper text identical to {', '.join(same)} apart from paper number/code"
    # exam_id uniqueness
    seen = defaultdict(list)
    for e in exams:
        seen[e['exam_id']].append(e)
    for k, v in seen.items():
        if len(v) > 1:
            raise SystemExit(f'duplicate exam_id {k}: {[x["qp_pdf"] for x in v]}')
    order = {'math': 0, 'physics': 1, 'economics': 2}
    exams.sort(key=lambda e: (order[e['subject']], e['year'], e['session'] != 'May', e['paper'],
                              e['option'] or '', e['tz'] or ''))
    return exams, skipped


def main():
    metas = load_meta('--no-cache' not in sys.argv)
    exams, skipped = build(metas)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w') as f:
        json.dump(exams, f, indent=2, ensure_ascii=False)
        f.write('\n')
    with open(os.path.join(SCRATCH, 'skipped.json'), 'w') as f:
        json.dump(skipped, f, indent=1, ensure_ascii=False)
    c = defaultdict(int)
    for e in exams:
        c[(e['subject'], e['syllabus'], e['paper'])] += 1
    for k in sorted(c):
        print(*k, c[k])
    print('exams:', len(exams), 'missing markscheme:', sum(1 for e in exams if not e['ms_pdf']),
          'skipped files:', len(skipped))


if __name__ == '__main__':
    if '--extract-only' in sys.argv:
        load_meta('--no-cache' not in sys.argv)
    else:
        main()
