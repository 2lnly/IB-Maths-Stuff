#!/usr/bin/env python3
"""
IB Math Exam Question Extractor

Extracts questions from IB Math exam papers as images,
paired with their corresponding markscheme answers.
"""

import argparse
import json
import re
import sys
from pathlib import Path

try:
    import fitz  # PyMuPDF
except ImportError:
    sys.exit("Error: PyMuPDF not installed. Run: pip install PyMuPDF")

try:
    from pdf2image import convert_from_path
except ImportError:
    sys.exit("Error: pdf2image not installed. Run: pip install pdf2image")

try:
    from PIL import Image
except ImportError:
    sys.exit("Error: Pillow not installed. Run: pip install Pillow")


def extract_question_pages(pdf_path: str, is_markscheme: bool = False) -> dict[int, list[int]]:
    """
    Extract question boundaries from a PDF.

    Returns mapping of question_number -> list of page indices (0-based).
    """
    doc = fitz.open(pdf_path)
    questions: dict[int, list[int]] = {}

    # First pass: find which pages contain each question marker
    page_questions: dict[int, list[int]] = {}  # page_num -> list of question numbers found

    for page_num in range(len(doc)):
        page = doc[page_num]
        text = page.get_text()

        # Skip instruction/cover pages
        lower_text = text.lower()
        if any(skip in lower_text for skip in [
            'do not open this examination paper',
            'instructions to candidates',
            'instructions to examiners',
            'this examination paper consists of',
            'using the markscheme',
            'abbreviations',
            'follow through marks',
            'implied marks',
        ]):
            continue

        if is_markscheme:
            # Markscheme: look for question start patterns
            # Real questions have (a) subparts and mark annotations like M1, A1
            # Pattern 1: "N." followed by newline then "(a)" on next line or same line
            matches = re.findall(r'^(\d{1,2})\.\s*\n\s*\(a\)', text, re.MULTILINE)
            if not matches:
                # Pattern 2: "N. (a)" on same line
                matches = re.findall(r'^(\d{1,2})\.\s+\(a\)', text, re.MULTILINE)
            if not matches:
                # Pattern 3: Question number with mark annotation nearby
                # Look for "N." followed within ~100 chars by M1, A1, or [N marks]
                for m in re.finditer(r'^(\d{1,2})\.\s*$', text, re.MULTILINE):
                    q_num = m.group(1)
                    # Check if there's mark content shortly after
                    rest = text[m.end():m.end()+200]
                    if re.search(r'[MA]\d|marks?\]|\(a\)', rest):
                        matches.append(q_num)
            if not matches:
                # Also check for "Question N continued"
                continued = re.search(r'Question\s+(\d{1,2})\s+continued', text)
                if continued:
                    matches = [continued.group(1)]
        else:
            # Exam paper pattern - "N. [Maximum mark: X]"
            matches = re.findall(r'^\s*(\d{1,2})\s*\.\s*\[Maximum mark:', text, re.MULTILINE)

        page_questions[page_num] = []
        for m in matches:
            q_num = int(m)
            if 1 <= q_num <= 20:
                page_questions[page_num].append(q_num)
                if q_num not in questions:
                    questions[q_num] = []
                if page_num not in questions[q_num]:
                    questions[q_num].append(page_num)

    # Second pass: handle multi-page questions
    if is_markscheme:
        # For markschemes, add "continued" pages to questions
        sorted_q_nums = sorted(questions.keys())
        for i, q_num in enumerate(sorted_q_nums):
            first_page = min(questions[q_num])
            # Find the end: page before next question
            if i + 1 < len(sorted_q_nums):
                next_q = sorted_q_nums[i + 1]
                end_page = min(questions[next_q]) - 1
            else:
                end_page = len(doc) - 1

            # Add intermediate pages that have "continued" or actual content
            for p in range(first_page + 1, end_page + 1):
                text = doc[p].get_text()
                # Check if this is a continuation page
                if f"Question {q_num} continued" in text or (
                    len(text.strip()) > 100 and
                    re.search(r'[MA]\d|marks?\]', text)
                ):
                    if p not in questions[q_num]:
                        questions[q_num].append(p)
    else:
        # For exam papers, questions may span multiple pages
        sorted_q_nums = sorted(questions.keys())
        for i, q_num in enumerate(sorted_q_nums):
            first_page = min(questions[q_num])
            # Find the end: either start of next question or end of doc
            if i + 1 < len(sorted_q_nums):
                next_q = sorted_q_nums[i + 1]
                end_page = min(questions[next_q]) - 1
            else:
                end_page = len(doc) - 1

            # Add intermediate pages
            for p in range(first_page, end_page + 1):
                if p not in questions[q_num]:
                    # Check it's not a blank/instruction page
                    text = doc[p].get_text()
                    if len(text.strip()) > 100:
                        questions[q_num].append(p)

    doc.close()

    # Sort pages for each question
    for q_num in questions:
        questions[q_num] = sorted(questions[q_num])

    return questions


def find_markscheme(exam_path: str) -> str | None:
    """
    Find the corresponding markscheme file for an exam paper.

    Exam: Mathematics_..._paper_N_...HL.pdf
    Markscheme: Mathematics_..._paper_N_...HL_markscheme.pdf
    """
    exam_path = Path(exam_path)
    exam_name = exam_path.stem
    exam_dir = exam_path.parent

    # The markscheme should have "_markscheme" suffix
    markscheme_name = f"{exam_name}_markscheme.pdf"
    markscheme_path = exam_dir / markscheme_name

    if markscheme_path.exists():
        return str(markscheme_path)

    return None


def convert_pages_to_images(
    pdf_path: str,
    pages: list[int],
    dpi: int = 200
) -> list[Image.Image]:
    """
    Convert specific pages of a PDF to PIL Images.

    Args:
        pdf_path: Path to PDF file
        pages: List of page indices (0-based)
        dpi: Resolution for output images

    Returns:
        List of PIL Image objects
    """
    images = []

    for page_num in pages:
        # pdf2image uses 1-based page numbers
        page_images = convert_from_path(
            pdf_path,
            dpi=dpi,
            first_page=page_num + 1,
            last_page=page_num + 1
        )
        if page_images:
            images.append(page_images[0])

    return images


def extract_exam(
    exam_path: str,
    output_dir: str,
    dpi: int = 200,
    verbose: bool = True
) -> dict:
    """
    Extract all questions from an exam paper with their markscheme answers.

    Args:
        exam_path: Path to exam PDF
        output_dir: Base output directory
        dpi: Image resolution
        verbose: Print progress messages

    Returns:
        Metadata dict with extraction results
    """
    exam_path = Path(exam_path)
    output_dir = Path(output_dir)

    if verbose:
        print(f"Processing: {exam_path.name}")

    # Parse exam filename to create output folder name
    # E.g., "Mathematics_analysis_and_approaches_paper_1__TZ1_HL.pdf"
    # -> year/PaperN/session_TZ/ structure

    session_match = re.search(r'(\d{4})\s+(May|November)', str(exam_path.parent))
    if session_match:
        year = session_match.group(1)
        session = session_match.group(2)
    else:
        year = "Unknown"
        session = "Unknown"

    # Extract paper number and timezone
    paper_match = re.search(r'paper[_\s]*(\d)', exam_path.name, re.IGNORECASE)
    paper_num = paper_match.group(1) if paper_match else "X"

    tz_match = re.search(r'TZ(\d)', exam_path.name)
    timezone = f"TZ{tz_match.group(1)}" if tz_match else ""

    # Create hierarchical folder structure: year/PaperN/session_TZ
    session_folder = session
    if timezone:
        session_folder += f"_{timezone}"

    exam_output_dir = output_dir / year / f"Paper{paper_num}" / session_folder
    exam_output_dir.mkdir(parents=True, exist_ok=True)

    # Find markscheme
    markscheme_path = find_markscheme(str(exam_path))
    if not markscheme_path:
        print(f"  Warning: No markscheme found for {exam_path.name}")

    # Extract question pages from exam
    if verbose:
        print("  Detecting questions in exam paper...")
    exam_questions = extract_question_pages(str(exam_path), is_markscheme=False)

    if not exam_questions:
        print(f"  Error: No questions detected in {exam_path.name}")
        return {"error": "No questions detected"}

    if verbose:
        print(f"  Found {len(exam_questions)} questions")

    # Extract question pages from markscheme
    ms_questions = {}
    if markscheme_path:
        if verbose:
            print("  Detecting questions in markscheme...")
        ms_questions = extract_question_pages(markscheme_path, is_markscheme=True)
        if verbose:
            print(f"  Found markscheme content for {len(ms_questions)} questions")

    metadata = {
        "exam_file": exam_path.name,
        "markscheme_file": Path(markscheme_path).name if markscheme_path else None,
        "year": year,
        "session": session,
        "timezone": timezone or None,
        "paper": paper_num,
        "questions": {}
    }

    # Process each question
    for q_num in sorted(exam_questions.keys()):
        if verbose:
            print(f"  Extracting Q{q_num}...")

        q_dir = exam_output_dir / f"Q{q_num}"
        q_dir.mkdir(exist_ok=True)

        q_metadata = {
            "question_pages": [],
            "answer_pages": []
        }

        # Convert exam pages to images
        exam_pages = exam_questions[q_num]
        exam_images = convert_pages_to_images(str(exam_path), exam_pages, dpi)

        for i, img in enumerate(exam_images):
            img_path = q_dir / f"question_p{i + 1}.png"
            img.save(str(img_path), "PNG")
            q_metadata["question_pages"].append(f"question_p{i + 1}.png")

        # Convert markscheme pages to images
        if q_num in ms_questions:
            ms_pages = ms_questions[q_num]
            ms_images = convert_pages_to_images(markscheme_path, ms_pages, dpi)

            for i, img in enumerate(ms_images):
                img_path = q_dir / f"answer_p{i + 1}.png"
                img.save(str(img_path), "PNG")
                q_metadata["answer_pages"].append(f"answer_p{i + 1}.png")

        metadata["questions"][str(q_num)] = q_metadata

    # Save metadata
    with open(exam_output_dir / "metadata.json", "w") as f:
        json.dump(metadata, f, indent=2)

    if verbose:
        print(f"  Output saved to: {exam_output_dir}")

    return metadata


def batch_extract(
    input_dir: str,
    output_dir: str,
    recursive: bool = True,
    dpi: int = 200,
    verbose: bool = True
) -> list[dict]:
    """
    Process all exam papers in a directory.

    Args:
        input_dir: Directory containing exam PDFs
        output_dir: Base output directory
        recursive: Search subdirectories
        dpi: Image resolution
        verbose: Print progress messages

    Returns:
        List of metadata dicts for each processed exam
    """
    input_dir = Path(input_dir)
    output_dir = Path(output_dir)

    # Find all exam PDFs (exclude markschemes and non-English variants)
    pattern = "**/*.pdf" if recursive else "*.pdf"
    all_pdfs = list(input_dir.glob(pattern))

    # Filter to only exam papers (not markschemes, not Spanish/French)
    exam_pdfs = []
    for pdf in all_pdfs:
        name = pdf.name.lower()
        # Skip markschemes
        if "markscheme" in name:
            continue
        # Skip non-English variants
        if any(lang in name for lang in ["spanish", "french", "français", "espanol"]):
            continue
        # Must be HL paper
        if "_hl" not in name:
            continue
        exam_pdfs.append(pdf)

    if verbose:
        print(f"Found {len(exam_pdfs)} exam papers to process")

    results = []
    for i, exam_path in enumerate(sorted(exam_pdfs)):
        if verbose:
            print(f"\n[{i + 1}/{len(exam_pdfs)}] ", end="")

        try:
            metadata = extract_exam(str(exam_path), str(output_dir), dpi, verbose)
            results.append(metadata)
        except Exception as e:
            print(f"Error processing {exam_path.name}: {e}")
            results.append({"error": str(e), "file": exam_path.name})

    return results


def main():
    parser = argparse.ArgumentParser(
        description="Extract questions from IB Math exam papers as images"
    )

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--exam",
        type=str,
        help="Path to a single exam PDF to process"
    )
    group.add_argument(
        "--input",
        type=str,
        help="Directory containing exam PDFs for batch processing"
    )

    parser.add_argument(
        "--output",
        type=str,
        default="output",
        help="Output directory (default: output/)"
    )
    parser.add_argument(
        "--dpi",
        type=int,
        default=200,
        help="Image resolution in DPI (default: 200)"
    )
    parser.add_argument(
        "--recursive",
        action="store_true",
        help="Search subdirectories when batch processing"
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress progress messages"
    )

    args = parser.parse_args()

    if args.exam:
        # Single file mode
        if not Path(args.exam).exists():
            sys.exit(f"Error: File not found: {args.exam}")
        extract_exam(args.exam, args.output, args.dpi, not args.quiet)
    else:
        # Batch mode
        if not Path(args.input).is_dir():
            sys.exit(f"Error: Directory not found: {args.input}")
        batch_extract(args.input, args.output, args.recursive, args.dpi, not args.quiet)


if __name__ == "__main__":
    main()
