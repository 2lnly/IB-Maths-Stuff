#!/usr/bin/env python3
"""
Extract individual questions from IB Physics HL PDFs.
Uses physics_pdf_catalog.json to find all papers, then splits each into individual questions.

For each question, saves:
- question_p1.png  (single merged image, always)
- question_text.txt
- answer_p1.png    (from markscheme)
- source_info.txt

Strategy:
- PDFs with text: regex-based question boundary detection on extracted text
- Scanned PDFs: full-page rendering, page-based splitting

Question IDs: PHY_P{N}_{year}_{session}_{tz}_Q{nn}
  e.g. PHY_P1_2023_May_TZ1_Q01
"""

import fitz  # PyMuPDF
import json
import os
import re
import sys
from PIL import Image
from io import BytesIO

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PRACTICE_DIR = os.path.join(BASE_DIR, "practice_physics")
DPI = 200
RENDER_MATRIX = fitz.Matrix(DPI / 72, DPI / 72)

# Pages to skip patterns (cover, instructions, blank)
SKIP_PATTERNS = [
    "do not open this examination paper",
    "please do not write on this page",
    "answers written on this page will not be marked",
    "instructions to candidates",
    "instructions to examiners",  # markscheme
    "abbreviations",  # markscheme instructions
]


def is_skip_page(text):
    """Check if a page is a cover/instruction/blank page."""
    text_lower = text.lower().strip()
    if len(text_lower) < 50:
        return True  # Nearly blank
    for pattern in SKIP_PATTERNS:
        if pattern in text_lower:
            # But if it also has a question number, don't skip
            if re.search(r'^\d+\.\s', text, re.MULTILINE):
                return False
            return True
    return False


def detect_question_boundaries_text(doc):
    """Detect question boundaries using text extraction (for PDFs with text layer).

    Returns list of dicts: {question_num, start_page, start_y, end_page, end_y}
    """
    questions = []

    for page_idx in range(doc.page_count):
        page = doc[page_idx]
        text = page.get_text("text")

        if is_skip_page(text):
            continue

        # Get text blocks with position info
        blocks = page.get_text("dict")["blocks"]

        for block in blocks:
            if block["type"] != 0:  # text block
                continue
            for line in block["lines"]:
                line_text = "".join(span["text"] for span in line["spans"]).strip()

                # Match question start: "1." or "1. [Maximum mark: 7]"
                q_match = re.match(r'^(\d+)\.\s*$', line_text)
                if not q_match:
                    q_match = re.match(r'^(\d+)\.\s', line_text)

                if q_match:
                    q_num = int(q_match.group(1))
                    y_pos = line["bbox"][1]  # top y coordinate

                    font_size = max((span["size"] for span in line["spans"]), default=10)

                    if font_size >= 9:  # Filter out small references
                        questions.append({
                            "question_num": q_num,
                            "start_page": page_idx,
                            "start_y": y_pos,
                            "font_size": font_size,
                        })

    # Deduplicate: keep only first occurrence of each question number
    seen = {}
    unique_questions = []
    for q in questions:
        num = q["question_num"]
        if num not in seen:
            seen[num] = q
            unique_questions.append(q)

    # Validate sequential ordering and filter false positives
    filtered = []
    expected_next = 1
    for q in sorted(unique_questions, key=lambda x: (x["start_page"], x["start_y"])):
        if q["question_num"] == expected_next or (q["question_num"] > expected_next and q["question_num"] <= expected_next + 2):
            filtered.append(q)
            expected_next = q["question_num"] + 1
        elif q["question_num"] == 1 and not filtered:
            filtered.append(q)
            expected_next = 2

    # Set end boundaries (each question ends where the next begins, or at doc end)
    for i in range(len(filtered)):
        if i + 1 < len(filtered):
            filtered[i]["end_page"] = filtered[i + 1]["start_page"]
            filtered[i]["end_y"] = filtered[i + 1]["start_y"]
        else:
            filtered[i]["end_page"] = doc.page_count - 1
            filtered[i]["end_y"] = doc[doc.page_count - 1].rect.height

    return filtered


def detect_question_boundaries_scan(doc):
    """For scanned PDFs with no text - render full pages.
    Each page after the cover pages is treated as containing one question entry.
    """
    questions = []
    content_pages = []

    for page_idx in range(doc.page_count):
        # For scanned PDFs, skip first 2 pages (cover + instructions)
        if page_idx < 2:
            continue
        content_pages.append(page_idx)

    for i, page_idx in enumerate(content_pages):
        questions.append({
            "question_num": i + 1,
            "start_page": page_idx,
            "start_y": 0,
            "end_page": page_idx,
            "end_y": doc[page_idx].rect.height,
            "is_scan": True,
        })

    return questions


def render_question_image(doc, start_page, start_y, end_page, end_y):
    """Render a question region as a single merged PIL Image.

    Stitches multi-page questions vertically into ONE image.
    """
    images = []

    for page_idx in range(start_page, end_page + 1):
        page = doc[page_idx]
        page_height = page.rect.height
        page_width = page.rect.width

        # Determine crop region
        if page_idx == start_page and page_idx == end_page:
            y0 = max(0, start_y - 10)
            y1 = end_y if end_y > y0 else page_height
            clip = fitz.Rect(0, y0, page_width, y1)
        elif page_idx == start_page:
            clip = fitz.Rect(0, max(0, start_y - 10), page_width, page_height)
        elif page_idx == end_page:
            y1 = end_y if end_y > 0 else page_height
            clip = fitz.Rect(0, 0, page_width, y1)
        else:
            clip = fitz.Rect(0, 0, page_width, page_height)

        # Skip invalid clips (zero or negative height)
        if clip.height <= 0:
            continue

        pix = page.get_pixmap(matrix=RENDER_MATRIX, clip=clip)
        img = Image.open(BytesIO(pix.tobytes("png")))
        images.append(img)

    if not images:
        return None

    if len(images) == 1:
        return images[0]

    # Stitch vertically into a single image
    total_width = max(img.width for img in images)
    total_height = sum(img.height for img in images)
    stitched = Image.new("RGB", (total_width, total_height), (255, 255, 255))
    y_offset = 0
    for img in images:
        stitched.paste(img, (0, y_offset))
        y_offset += img.height

    return stitched


def extract_question_text(doc, start_page, start_y, end_page, end_y):
    """Extract text for a question region."""
    texts = []

    for page_idx in range(start_page, end_page + 1):
        page = doc[page_idx]
        page_height = page.rect.height
        page_width = page.rect.width

        if page_idx == start_page and page_idx == end_page:
            y0 = max(0, start_y - 5)
            y1 = end_y if end_y > y0 else page_height
            clip = fitz.Rect(0, y0, page_width, y1)
        elif page_idx == start_page:
            clip = fitz.Rect(0, max(0, start_y - 5), page_width, page_height)
        elif page_idx == end_page:
            y1 = end_y if end_y > 0 else page_height
            clip = fitz.Rect(0, 0, page_width, y1)
        else:
            clip = fitz.Rect(0, 0, page_width, page_height)

        if clip.height <= 0:
            continue

        text = page.get_text("text", clip=clip)
        # Clean up common artifacts
        text = re.sub(r'Turn over\s*', '', text)
        text = re.sub(r'– \d+ –', '', text)
        text = re.sub(r'[A-Z]\d+/\d+/[A-Z]+/[A-Z]+\d*/[A-Z]+/[A-Z]+\d*/[A-Z]+/?[A-Z]*', '', text)
        text = re.sub(r'\d{4}EP\d{2}', '', text)
        text = re.sub(r'\d{4}\s*–\s*\d{4}', '', text)
        texts.append(text.strip())

    return "\n".join(texts)


def extract_marks_from_text(question_text):
    """Extract marks from [Maximum mark: N] in question text."""
    match = re.search(r'\[Maximum mark:\s*(\d+)\]', question_text)
    if match:
        return int(match.group(1))
    return None


def find_markscheme_content_start(ms_doc):
    """Find the first page index where actual question answers begin."""
    # Pass 1: "Section A/B" header — most reliable for pre-2019 format
    for page_idx in range(ms_doc.page_count):
        text = ms_doc[page_idx].get_text("text")
        if re.search(r'^\s*Section\s+[AB]\s*$', text, re.MULTILINE):
            return page_idx

    # Pass 2: identify all instruction/preamble pages to skip past them
    INSTRUCTION_KEYWORDS = [
        'mark allocation', 'subject details', 'abbreviations',
        'instructions to examiners', 'each row in the', 'marking point',
        'generic markscheme', 'it is the property of the international baccalaureate',
    ]
    instruction_pages = set()
    for page_idx in range(ms_doc.page_count):
        text = ms_doc[page_idx].get_text("text").lower()
        if any(kw in text for kw in INSTRUCTION_KEYWORDS):
            instruction_pages.add(page_idx)

    instructions_end = (max(instruction_pages) + 1) if instruction_pages else 0

    # Pass 3a: table format — find first page with "Question / Answers / Notes" headers
    # (handles both cases: instruction pages found or not)
    for page_idx in range(ms_doc.page_count):
        text = ms_doc[page_idx].get_text("text")
        if re.search(r'Question\s*\n\s*Answers\s*\n\s*Notes', text):
            return page_idx

    # Pass 3b: first non-instruction page that starts with "1." (question 1)
    for page_idx in range(instructions_end, ms_doc.page_count):
        blocks = ms_doc[page_idx].get_text("dict")["blocks"]
        for block in blocks:
            if block["type"] != 0:
                continue
            for line in block["lines"]:
                line_text = "".join(span["text"] for span in line["spans"]).strip()
                font_size = max((span["size"] for span in line["spans"]), default=10)
                if (re.match(r'^1\.\s*$', line_text) or re.match(r'^1\.\s\S', line_text)) and font_size >= 8:
                    return page_idx

    # Fallback: skip first 6 pages
    return min(6, ms_doc.page_count - 1)


def detect_markscheme_boundaries(ms_doc):
    """Detect question boundaries in a markscheme PDF."""
    questions = {}
    content_start = find_markscheme_content_start(ms_doc)

    # Detect if this is a table-format markscheme (2016–2017 style: no period after q_num)
    # These have "Question | Answers | Notes | Total" as a repeating page header
    is_table_format = False
    for page_idx in range(content_start, min(content_start + 3, ms_doc.page_count)):
        text = ms_doc[page_idx].get_text("text")
        if re.search(r'Question\s*\n\s*Answers\s*\n\s*Notes', text):
            is_table_format = True
            break

    if is_table_format:
        # Scan each page's text for standalone question numbers.
        # The table repeats "Question / Answers / Notes / Total" as a header row on each page.
        # A new top-level question number appears immediately after that header row.
        # Questions can also start mid-page (after the previous question ends).
        #
        # Two-pass approach:
        #  Pass 1 (reliable): "Notes\nTotal\n<int>" at page tops — unambiguous Q starts.
        #  Pass 2 (mid-page): standalone integers preceded by non-formula-token lines,
        #                     followed by a sub-part label [a-h] or 'ALTERNATIVE'.

        TABLE_BOILERPLATE = {'question', 'answers', 'notes', 'total', ''}
        HEADER_SKIP = [
            re.compile(r'^[–\-]\s*\d+\s*[–\-]$'),
            re.compile(r'^[A-Z]\d{2}/\d+/'),
            re.compile(r'^\d+ pages?$', re.IGNORECASE),
            re.compile(r'^\(question \d+', re.IGNORECASE),
        ]

        def is_formula_token(s):
            """Short token that looks like a formula element (number, unit, symbol)."""
            if not s or s.lower() in TABLE_BOILERPLATE:
                return False
            if any(p.match(s) for p in HEADER_SKIP):
                return False
            if len(s) > 12 or ' ' in s:
                return False  # longer text is answer content, not formula
            return True  # short token

        # Pass 1: page-top Qs via "Notes/Total/<int>/<letter-or-content>" pattern
        for page_idx in range(content_start, ms_doc.page_count):
            text = ms_doc[page_idx].get_text("text")
            for m in re.finditer(
                r'Notes\s*\n\s*Total\s*\n\s*(\d+)\.?\s*\n\s*\(?([a-zA-Z])',
                text
            ):
                q_num = int(m.group(1))
                if 1 <= q_num <= 30 and q_num not in questions:
                    questions[q_num] = {
                        "question_num": q_num,
                        "start_page": page_idx,
                        "start_y": 0,
                    }

        # Pass 2: mid-page Qs — integer followed by [a-h] sub-part (with context check)
        for page_idx in range(content_start, ms_doc.page_count):
            lines = [l.strip() for l in ms_doc[page_idx].get_text("text").split('\n')]
            for i, stripped in enumerate(lines):
                if not stripped or stripped.lower() in TABLE_BOILERPLATE:
                    continue
                if any(p.match(stripped) for p in HEADER_SKIP):
                    continue
                if not re.match(r'^\d+\.?$', stripped):
                    continue
                q_num = int(stripped.rstrip('.'))
                if not (1 <= q_num <= 30) or q_num in questions:
                    continue

                prev = lines[i - 1] if i > 0 else ''

                # Find next non-empty line
                nxt = ''
                nxt_idx = i + 1
                for j in range(i + 1, min(i + 5, len(lines))):
                    if lines[j]:
                        nxt = lines[j]
                        nxt_idx = j
                        break

                if not nxt:
                    continue

                is_subpart = bool(re.match(r'^\(?[a-h]\)?$', nxt))
                is_alt = nxt.upper().startswith('ALTERNATIVE')
                # Long answer text directly after Q num (no sub-part label), only valid
                # when prev is not a formula token (prevents matching mid-formula numbers)
                is_long_content = (
                    len(nxt) > 15 and ' ' in nxt and not is_formula_token(prev)
                )

                if not (is_subpart or is_alt or is_long_content):
                    continue

                if is_formula_token(prev):
                    if is_subpart or is_alt:
                        # Check next_next: must be content (not a formula operator)
                        next_next = ''
                        for k in range(nxt_idx + 1, min(nxt_idx + 5, len(lines))):
                            if lines[k]:
                                next_next = lines[k]
                                break
                        is_content = (
                            len(next_next) > 6 or
                            ' ' in next_next or
                            re.match(r'^i{1,4}v?$', next_next) or   # roman numeral
                            re.match(r'^\d{2,}', next_next)          # 2+ digit number
                        )
                        if not is_content:
                            continue

                questions[q_num] = {
                    "question_num": q_num,
                    "start_page": page_idx,
                    "start_y": 0,
                }
    else:
        for page_idx in range(content_start, ms_doc.page_count):
            page = ms_doc[page_idx]
            blocks = page.get_text("dict")["blocks"]
            for block in blocks:
                if block["type"] != 0:
                    continue
                for line in block["lines"]:
                    line_text = "".join(span["text"] for span in line["spans"]).strip()

                    q_match = re.match(r'^(\d+)\.\s*$', line_text)
                    if not q_match:
                        q_match = re.match(r'^(\d+)\.\s', line_text)

                    if q_match:
                        q_num = int(q_match.group(1))
                        font_size = max((span["size"] for span in line["spans"]), default=10)
                        y_pos = line["bbox"][1]

                        if font_size >= 8 and q_num <= 30 and q_num not in questions:
                            questions[q_num] = {
                                "question_num": q_num,
                                "start_page": page_idx,
                                "start_y": y_pos,
                            }

    # Sort and set end boundaries
    sorted_qs = sorted(questions.values(), key=lambda x: (x["start_page"], x["start_y"]))
    for i in range(len(sorted_qs)):
        if i + 1 < len(sorted_qs):
            next_q = sorted_qs[i + 1]
            if is_table_format:
                # Table-format: all start_y=0, so end at the last full page before next Q.
                # If the next Q is on a later page, end at the page before it.
                # If the next Q is on the same page, give the current Q the whole page.
                if next_q["start_page"] > sorted_qs[i]["start_page"]:
                    end_pg = next_q["start_page"] - 1
                    sorted_qs[i]["end_page"] = end_pg
                    sorted_qs[i]["end_y"] = ms_doc[end_pg].rect.height
                else:
                    sorted_qs[i]["end_page"] = sorted_qs[i]["start_page"]
                    sorted_qs[i]["end_y"] = ms_doc[sorted_qs[i]["start_page"]].rect.height
            else:
                sorted_qs[i]["end_page"] = next_q["start_page"]
                sorted_qs[i]["end_y"] = next_q["start_y"]
        else:
            sorted_qs[i]["end_page"] = ms_doc.page_count - 1
            sorted_qs[i]["end_y"] = ms_doc[ms_doc.page_count - 1].rect.height

    return {q["question_num"]: q for q in sorted_qs}


def make_question_id(entry, question_num):
    """Generate a unique question ID from catalog entry + question number.

    Format: PHY_P{N}_{year}_{session}_{tz}_Q{nn}
    e.g. PHY_P1_2023_May_TZ1_Q01
    """
    paper_num = entry["paper"].split()[-1]  # "1", "2", or "3"
    parts = [f"PHY_P{paper_num}"]
    parts.append(str(entry["year"]))
    parts.append(entry["session"])
    if entry["tz"]:
        parts.append(entry["tz"])
    parts.append(f"Q{question_num:02d}")
    return "_".join(parts)


def process_paper(entry, force=False):
    """Process a single paper: extract all questions and their markscheme answers."""
    pdf_path = os.path.join(BASE_DIR, entry["pdf_path"])
    ms_path = os.path.join(BASE_DIR, entry["markscheme_path"]) if entry["markscheme_path"] else None

    paper_num = entry["paper"].split()[-1]
    paper_folder = f"paper {paper_num}"

    results = []

    try:
        doc = fitz.open(pdf_path)
    except Exception as e:
        print(f"  ERROR opening {entry['pdf_path']}: {e}")
        return results

    # Check if this is a scanned PDF
    total_text = sum(len(doc[i].get_text("text").strip()) for i in range(min(5, doc.page_count)))
    is_scan = total_text < 200

    if is_scan:
        questions = detect_question_boundaries_scan(doc)
    else:
        questions = detect_question_boundaries_text(doc)

    if not questions:
        print(f"  WARNING: No questions found in {entry['pdf_path']}")
        doc.close()
        return results

    # Open markscheme
    ms_doc = None
    ms_boundaries = {}
    if ms_path and os.path.exists(ms_path):
        try:
            ms_doc = fitz.open(ms_path)
            if not is_scan:
                ms_boundaries = detect_markscheme_boundaries(ms_doc)
        except Exception as e:
            print(f"  WARNING: Could not open markscheme: {e}")

    for q in questions:
        q_num = q["question_num"]
        q_id = make_question_id(entry, q_num)

        # Create output directory
        out_dir = os.path.join(PRACTICE_DIR, paper_folder, q_id)

        if os.path.exists(out_dir) and not force:
            results.append(q_id)
            continue

        os.makedirs(out_dir, exist_ok=True)

        # Render question image as single merged image
        img = render_question_image(
            doc, q["start_page"], q["start_y"],
            q["end_page"], q["end_y"]
        )
        if img:
            img.save(os.path.join(out_dir, "question_p1.png"), "PNG")

        # Extract question text and marks
        marks = None
        if not is_scan:
            text = extract_question_text(
                doc, q["start_page"], q["start_y"],
                q["end_page"], q["end_y"]
            )
            with open(os.path.join(out_dir, "question_text.txt"), "w") as f:
                f.write(text)
            marks = extract_marks_from_text(text)

        # Extract markscheme answer as single merged image
        if ms_doc and q_num in ms_boundaries:
            ms_q = ms_boundaries[q_num]
            ms_img = render_question_image(
                ms_doc, ms_q["start_page"], ms_q["start_y"],
                ms_q["end_page"], ms_q["end_y"]
            )
            if ms_img:
                ms_img.save(os.path.join(out_dir, "answer_p1.png"), "PNG")
        elif ms_doc and is_scan:
            # For scanned markschemes, render corresponding page (approximate)
            ms_page_idx = q["start_page"]
            if ms_page_idx < ms_doc.page_count:
                pix = ms_doc[ms_page_idx].get_pixmap(matrix=RENDER_MATRIX)
                ms_img = Image.open(BytesIO(pix.tobytes("png")))
                ms_img.save(os.path.join(out_dir, "answer_p1.png"), "PNG")

        # Write source info
        with open(os.path.join(out_dir, "source_info.txt"), "w") as f:
            f.write(f"Year: {entry['year']}\n")
            session_str = entry["session"]
            if entry["tz"]:
                session_str += f"_{entry['tz']}"
            f.write(f"Session: {session_str}\n")
            f.write(f"Original Question: Q{q_num}\n")
            f.write(f"Paper: {entry['paper']}\n")
            if marks:
                f.write(f"Marks: {marks}\n")
            f.write(f"Curriculum: {entry['curriculum']}\n")
            f.write(f"Is Scan: {is_scan}\n")

        results.append(q_id)

    doc.close()
    if ms_doc:
        ms_doc.close()

    return results


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Extract questions from IB Physics HL PDFs")
    parser.add_argument("--paper", type=int, choices=[1, 2, 3], help="Only process this paper number")
    parser.add_argument("--year", type=int, help="Only process this year")
    parser.add_argument("--force", action="store_true", help="Re-extract even if output exists")
    parser.add_argument("--limit", type=int, help="Process only N papers (for testing)")
    args = parser.parse_args()

    # Load catalog
    catalog_path = os.path.join(BASE_DIR, "data", "physics_pdf_catalog.json")
    if not os.path.exists(catalog_path):
        print(f"ERROR: Catalog not found at {catalog_path}")
        print("Run scripts/catalog_physics_pdfs.py first.")
        sys.exit(1)

    with open(catalog_path) as f:
        catalog = json.load(f)

    # Filter
    if args.paper:
        catalog = [e for e in catalog if e["paper"] == f"Paper {args.paper}"]
    if args.year:
        catalog = [e for e in catalog if e["year"] == args.year]
    if args.limit:
        catalog = catalog[:args.limit]

    print(f"Processing {len(catalog)} papers...")
    os.makedirs(PRACTICE_DIR, exist_ok=True)

    all_questions = []
    errors = []

    for i, entry in enumerate(catalog):
        label = f"{entry['paper']} {entry['year']} {entry['session']}"
        if entry["tz"]:
            label += f" {entry['tz']}"

        print(f"[{i+1}/{len(catalog)}] {label}...", end=" ", flush=True)

        try:
            questions = process_paper(entry, force=args.force)
            print(f"{len(questions)} questions")
            all_questions.extend(questions)
        except Exception as e:
            print(f"ERROR: {e}")
            errors.append({"paper": label, "error": str(e)})

    print(f"\n=== Physics Extraction Summary ===")
    print(f"Total questions extracted: {len(all_questions)}")
    print(f"Errors: {len(errors)}")
    for err in errors:
        print(f"  - {err['paper']}: {err['error']}")

    # Save extraction manifest
    manifest_path = os.path.join(BASE_DIR, "data", "physics_extraction_manifest.json")
    os.makedirs(os.path.dirname(manifest_path), exist_ok=True)
    with open(manifest_path, "w") as f:
        json.dump({
            "total_questions": len(all_questions),
            "question_ids": all_questions,
            "errors": errors,
        }, f, indent=2)
    print(f"Manifest saved to {manifest_path}")


if __name__ == "__main__":
    main()
