#!/usr/bin/env python3
"""
Extract individual questions from IB Math HL PDFs.
Uses pdf_catalog.json to find all papers, then splits each into individual questions.

For each question, saves:
- question_p1.png (and p2, p3... if multi-page)
- question_text.txt
- answer_p1.png (from markscheme)
- source_info.txt

Strategy:
- 2002+ PDFs: regex-based question boundary detection on extracted text
- 1997-2001 PDFs: full-page rendering, Claude Haiku vision for boundary detection
"""

import fitz  # PyMuPDF
import json
import os
import re
import sys
from PIL import Image
from io import BytesIO

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PRACTICE_DIR = os.path.join(BASE_DIR, "practice_new")  # New extraction dir
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
    """Detect question boundaries using text extraction (for 2002+ PDFs).

    Returns list of dicts: {question_num, start_page, start_y, end_page, end_y, marks}
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
                # Must be at the start of a line, standalone number
                q_match = re.match(r'^(\d+)\.\s*$', line_text)
                if not q_match:
                    q_match = re.match(r'^(\d+)\.\s', line_text)

                if q_match:
                    q_num = int(q_match.group(1))
                    y_pos = line["bbox"][1]  # top y coordinate

                    # Look for [Maximum mark: N] nearby (same page, within ~50 units)
                    marks = None
                    mark_match = re.search(r'\[Maximum mark:\s*(\d+)\]', text)
                    # Search in nearby text blocks too
                    page_text = page.get_text("text")
                    all_marks = re.findall(r'\[Maximum mark:\s*(\d+)\]', page_text)

                    # Check if this is a genuine new question (not a sub-question reference)
                    # Questions are numbered sequentially, and usually > font size threshold
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
        # Allow some gaps but questions should be roughly sequential
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
    """For scanned PDFs (1997-2001) with no text - render full pages.
    Each page after the cover pages is treated as containing questions.
    We'll do simple page-based splitting since we can't detect boundaries without OCR.
    """
    questions = []
    content_pages = []

    for page_idx in range(doc.page_count):
        page = doc[page_idx]
        text = page.get_text("text").strip()

        # For scanned PDFs, skip first 2 pages (cover + instructions)
        if page_idx < 2:
            continue

        content_pages.append(page_idx)

    # For scanned PDFs, we'll render each content page as a separate "question"
    # and rely on Claude Haiku classification later to properly identify them
    # This is a simplification - each page becomes one entry
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
    """Render a question region as a PIL Image.

    If the question spans multiple pages, stitch them vertically.
    """
    images = []

    for page_idx in range(start_page, end_page + 1):
        page = doc[page_idx]
        page_height = page.rect.height
        page_width = page.rect.width

        # Determine crop region
        if page_idx == start_page and page_idx == end_page:
            # Single page question - crop from start_y to end_y
            clip = fitz.Rect(0, max(0, start_y - 10), page_width, end_y)
        elif page_idx == start_page:
            # First page of multi-page - from start_y to bottom
            clip = fitz.Rect(0, max(0, start_y - 10), page_width, page_height)
        elif page_idx == end_page:
            # Last page - from top to end_y
            clip = fitz.Rect(0, 0, page_width, end_y)
        else:
            # Middle page - full page
            clip = fitz.Rect(0, 0, page_width, page_height)

        pix = page.get_pixmap(matrix=RENDER_MATRIX, clip=clip)
        img = Image.open(BytesIO(pix.tobytes("png")))
        images.append(img)

    if not images:
        return None

    if len(images) == 1:
        return images[0]

    # Stitch vertically
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
            clip = fitz.Rect(0, max(0, start_y - 5), page_width, end_y)
        elif page_idx == start_page:
            clip = fitz.Rect(0, max(0, start_y - 5), page_width, page_height)
        elif page_idx == end_page:
            clip = fitz.Rect(0, 0, page_width, end_y)
        else:
            clip = fitz.Rect(0, 0, page_width, page_height)

        text = page.get_text("text", clip=clip)
        # Clean up common artifacts
        text = re.sub(r'Turn over\s*', '', text)
        text = re.sub(r'– \d+ –', '', text)
        text = re.sub(r'[A-Z]\d+/\d+/[A-Z]+/[A-Z]+\d*/[A-Z]+/[A-Z]+\d*/[A-Z]+/?[A-Z]*', '', text)  # exam codes
        text = re.sub(r'\d{4}EP\d{2}', '', text)  # page codes
        text = re.sub(r'\d{4}\s*–\s*\d{4}', '', text)  # session codes like 2223-7106
        texts.append(text.strip())

    return "\n".join(texts)


def extract_marks_from_markscheme(ms_doc, question_num):
    """Extract total marks for a question from the markscheme PDF."""
    for page_idx in range(ms_doc.page_count):
        text = ms_doc[page_idx].get_text("text")
        # Look for "Total [N marks]" pattern after the question number
        patterns = [
            rf'Total\s*\[(\d+)\s*marks?\]',
            rf'\[(\d+)\s*marks?\]\s*$',
        ]
        # Find sections for this question
        q_pattern = rf'(?:^|\n)\s*{question_num}\.\s'
        q_matches = list(re.finditer(q_pattern, text))
        if q_matches:
            # Get text from this question to next question
            start = q_matches[0].start()
            next_q = re.search(rf'(?:^|\n)\s*{question_num + 1}\.\s', text[start + 10:])
            end = start + 10 + next_q.start() if next_q else len(text)
            section = text[start:end]

            # Find total marks in this section
            total_match = re.search(r'Total\s*\[(\d+)\s*marks?\]', section)
            if total_match:
                return int(total_match.group(1))

            # Count all [N marks] in section
            all_marks = re.findall(r'\[(\d+)\s*marks?\]', section)
            if all_marks:
                return sum(int(m) for m in all_marks)

    return None


def find_markscheme_content_start(ms_doc):
    """Find the first page index where actual question answers begin.

    Strategy: look for "Section A" (preferred), then "Section B",
    then "1." near top of page after instructions are done.
    """
    # Pass 1: find "Section A" or "Section B" - most reliable signal
    for page_idx in range(ms_doc.page_count):
        text = ms_doc[page_idx].get_text("text")
        if re.search(r'^\s*Section\s+[AB]\s*$', text, re.MULTILINE):
            return page_idx

    # Pass 2: find page where "1." is a top-level question header
    # Only look after instruction pages are done (i.e., after page that has "Abbreviations")
    instructions_end = 0
    for page_idx in range(ms_doc.page_count):
        text = ms_doc[page_idx].get_text("text").lower()
        if "abbreviations" in text or "instructions to examiners" in text:
            instructions_end = page_idx + 1

    for page_idx in range(instructions_end, ms_doc.page_count):
        blocks = ms_doc[page_idx].get_text("dict")["blocks"]
        for block in blocks:
            if block["type"] != 0:
                continue
            for line in block["lines"]:
                line_text = "".join(span["text"] for span in line["spans"]).strip()
                y_pos = line["bbox"][1]
                font_size = max((span["size"] for span in line["spans"]), default=10)
                # "1." standalone near top of page, not tiny text
                if (re.match(r'^1\.\s*$', line_text) or re.match(r'^1\.\s\S', line_text)) and font_size >= 10:
                    return page_idx

    # Fallback: skip first 6 pages
    return min(6, ms_doc.page_count - 1)


def detect_markscheme_boundaries(ms_doc):
    """Detect question boundaries in a markscheme PDF."""
    questions = {}
    content_start = find_markscheme_content_start(ms_doc)

    for page_idx in range(content_start, ms_doc.page_count):
        page = ms_doc[page_idx]
        text = page.get_text("text")

        blocks = page.get_text("dict")["blocks"]
        for block in blocks:
            if block["type"] != 0:
                continue
            for line in block["lines"]:
                line_text = "".join(span["text"] for span in line["spans"]).strip()

                # Markscheme question headers: standalone "N." at start of line
                q_match = re.match(r'^(\d+)\.\s*$', line_text)
                if not q_match:
                    q_match = re.match(r'^(\d+)\.\s', line_text)

                if q_match:
                    q_num = int(q_match.group(1))
                    font_size = max((span["size"] for span in line["spans"]), default=10)
                    y_pos = line["bbox"][1]

                    # Must be >= font 9pt and question number <= 30 (max questions per paper)
                    if font_size >= 9 and q_num <= 30 and q_num not in questions:
                        questions[q_num] = {
                            "question_num": q_num,
                            "start_page": page_idx,
                            "start_y": y_pos,
                        }

    # Sort and set end boundaries
    sorted_qs = sorted(questions.values(), key=lambda x: (x["start_page"], x["start_y"]))
    for i in range(len(sorted_qs)):
        if i + 1 < len(sorted_qs):
            sorted_qs[i]["end_page"] = sorted_qs[i + 1]["start_page"]
            sorted_qs[i]["end_y"] = sorted_qs[i + 1]["start_y"]
        else:
            sorted_qs[i]["end_page"] = ms_doc.page_count - 1
            sorted_qs[i]["end_y"] = ms_doc[ms_doc.page_count - 1].rect.height

    return {q["question_num"]: q for q in sorted_qs}


def make_question_id(entry, question_num):
    """Generate a unique question ID from catalog entry + question number."""
    parts = [f"P{entry['paper'].split()[-1]}"]
    parts.append(str(entry["year"]))
    parts.append(entry["session"])
    if entry["tz"]:
        parts.append(entry["tz"])
    if entry.get("paper3_option"):
        # Shorten option names
        opt_map = {
            "Calculus": "Calc",
            "Discrete_mathematics": "Discrete",
            "Series_and_differential_equations": "SeriesDiffEq",
            "Sets_relations_and_groups": "SetsGroups",
            "Statistics_and_probability": "StatProb",
        }
        parts.append(opt_map.get(entry["paper3_option"], entry["paper3_option"]))
    parts.append(f"Q{question_num:02d}")
    return "_".join(parts)


def process_paper(entry, force=False):
    """Process a single paper: extract all questions and their markscheme answers."""
    pdf_path = os.path.join(BASE_DIR, entry["pdf_path"])
    ms_path = os.path.join(BASE_DIR, entry["markscheme_path"]) if entry["markscheme_path"] else None

    paper_folder = f"paper {entry['paper'].split()[-1]}"

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

        # Render question image
        img = render_question_image(
            doc, q["start_page"], q["start_y"],
            q["end_page"], q["end_y"]
        )
        if img:
            img.save(os.path.join(out_dir, "question_p1.png"), "PNG")

        # Extract question text
        if not is_scan:
            text = extract_question_text(
                doc, q["start_page"], q["start_y"],
                q["end_page"], q["end_y"]
            )
            with open(os.path.join(out_dir, "question_text.txt"), "w") as f:
                f.write(text)

        # Extract markscheme answer
        if ms_doc and q_num in ms_boundaries:
            ms_q = ms_boundaries[q_num]
            ms_img = render_question_image(
                ms_doc, ms_q["start_page"], ms_q["start_y"],
                ms_q["end_page"], ms_q["end_y"]
            )
            if ms_img:
                ms_img.save(os.path.join(out_dir, "answer_p1.png"), "PNG")
        elif ms_doc and is_scan:
            # For scanned markschemes, render corresponding page
            # This is approximate - scan pages may not align 1:1
            ms_page_idx = q["start_page"]
            if ms_page_idx < ms_doc.page_count:
                pix = ms_doc[ms_page_idx].get_pixmap(matrix=RENDER_MATRIX)
                ms_img = Image.open(BytesIO(pix.tobytes("png")))
                ms_img.save(os.path.join(out_dir, "answer_p1.png"), "PNG")

        # Extract marks from markscheme
        marks = None
        if ms_doc and not is_scan:
            marks = extract_marks_from_markscheme(ms_doc, q_num)

        # Write source info
        with open(os.path.join(out_dir, "source_info.txt"), "w") as f:
            f.write(f"Year: {entry['year']}\n")
            session_str = entry["session"]
            if entry["tz"]:
                session_str += f"_{entry['tz']}"
            f.write(f"Session: {session_str}\n")
            f.write(f"Original Question: Q{q_num}\n")
            f.write(f"Paper: {entry['paper']}\n")
            if entry.get("paper3_option"):
                f.write(f"Paper 3 Option: {entry['paper3_option']}\n")
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
    parser = argparse.ArgumentParser(description="Extract questions from IB Math PDFs")
    parser.add_argument("--paper", type=int, choices=[1, 2, 3], help="Only process this paper number")
    parser.add_argument("--year", type=int, help="Only process this year")
    parser.add_argument("--force", action="store_true", help="Re-extract even if output exists")
    parser.add_argument("--limit", type=int, help="Process only N papers (for testing)")
    args = parser.parse_args()

    # Load catalog
    catalog_path = os.path.join(BASE_DIR, "data", "pdf_catalog.json")
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
        if entry.get("paper3_option"):
            label += f" ({entry['paper3_option']})"

        print(f"[{i+1}/{len(catalog)}] {label}...", end=" ", flush=True)

        try:
            questions = process_paper(entry, force=args.force)
            print(f"{len(questions)} questions")
            all_questions.extend(questions)
        except Exception as e:
            print(f"ERROR: {e}")
            errors.append({"paper": label, "error": str(e)})

    print(f"\n=== Extraction Summary ===")
    print(f"Total questions extracted: {len(all_questions)}")
    print(f"Errors: {len(errors)}")
    for err in errors:
        print(f"  - {err['paper']}: {err['error']}")

    # Save extraction manifest
    manifest_path = os.path.join(BASE_DIR, "data", "extraction_manifest.json")
    with open(manifest_path, "w") as f:
        json.dump({
            "total_questions": len(all_questions),
            "question_ids": all_questions,
            "errors": errors,
        }, f, indent=2)
    print(f"Manifest saved to {manifest_path}")


if __name__ == "__main__":
    main()
