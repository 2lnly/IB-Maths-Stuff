"""
Economics SL Paper Organizer
Organizes questions by type: 15 markers, 10 markers, and case studies
"""

import json
import re
import subprocess
from pathlib import Path
from collections import defaultdict

# Paths
ECON_DIR = Path(__file__).parent.parent / "Economics SL"
OUTPUT_DIR = Path(__file__).parent.parent / "Economics Organized"
RESULTS_FILE = Path(__file__).parent / "economics_classification_results.json"

def extract_pdf_text(pdf_path):
    """Extract text from PDF using pdftotext."""
    try:
        result = subprocess.run(
            ['pdftotext', str(pdf_path), '-'],
            capture_output=True,
            text=True,
            timeout=30
        )
        return result.stdout
    except Exception as e:
        print(f"Error extracting text from {pdf_path}: {e}")
        return ""

def extract_pdf_pages_as_images(pdf_path, output_dir, prefix):
    """Extract PDF pages as PNG images."""
    output_dir.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(
            ['pdftoppm', '-png', str(pdf_path), str(output_dir / prefix)],
            check=True,
            timeout=60
        )
        return True
    except Exception as e:
        print(f"Error converting PDF to images: {e}")
        return False

def parse_paper1(pdf_path, text, year, session, tz=""):
    """Parse Paper 1 - extract 10 and 15 markers with topic classification."""
    questions = []

    # Detect topics by looking for section headers
    # Common patterns: "Microeconomics", "Macroeconomics", "International economics", "Development economics"
    topic_map = {}

    # Find topic positions in text
    micro_match = re.search(r'(Microeconomics|MICROECONOMICS)', text)
    macro_match = re.search(r'(Macroeconomics|MACROECONOMICS)', text)
    intl_match = re.search(r'(International economics|INTERNATIONAL ECONOMICS)', text, re.IGNORECASE)
    dev_match = re.search(r'(Development economics|DEVELOPMENT ECONOMICS)', text, re.IGNORECASE)

    # Map question numbers to topics based on typical Paper 1 structure
    # Questions 1-2 are typically under first topic (usually Microeconomics)
    # Questions 3-4 are typically under second topic (Macroeconomics/International/Development)

    if micro_match and macro_match:
        # Standard structure: Q1-2 Micro, Q3-4 Macro
        topic_map = {
            '1': 'Microeconomics',
            '2': 'Microeconomics',
            '3': 'Macroeconomics',
            '4': 'Macroeconomics'
        }
    elif micro_match and intl_match:
        topic_map = {
            '1': 'Microeconomics',
            '2': 'Microeconomics',
            '3': 'International Economics',
            '4': 'International Economics'
        }
    elif micro_match and dev_match:
        topic_map = {
            '1': 'Microeconomics',
            '2': 'Microeconomics',
            '3': 'Development Economics',
            '4': 'Development Economics'
        }
    else:
        # Default mapping
        topic_map = {
            '1': 'Microeconomics',
            '2': 'Microeconomics',
            '3': 'Macroeconomics',
            '4': 'Macroeconomics'
        }

    # Split into sections
    sections = re.split(r'\n(\d+)\.\s+', text)

    for i in range(1, len(sections), 2):
        q_num = sections[i]
        q_text = sections[i + 1] if i + 1 < len(sections) else ""

        # Get topic for this question number
        topic = topic_map.get(q_num, 'Unknown')

        # Find (a) part [10 marks]
        part_a_match = re.search(r'\(a\)\s+(.*?)\s+\[10\]', q_text, re.DOTALL)
        # Find (b) part [15 marks]
        part_b_match = re.search(r'\(b\)\s+(.*?)\s+\[15\]', q_text, re.DOTALL)

        if part_a_match:
            questions.append({
                'question_num': f"Q{q_num}a",
                'marks': 10,
                'type': '10_marker',
                'topic': topic,
                'paper': 'Paper 1',
                'year': year,
                'session': session,
                'tz': tz,
                'text': part_a_match.group(1).strip()[:200],  # First 200 chars for description
                'pdf_path': str(pdf_path)
            })

        if part_b_match:
            questions.append({
                'question_num': f"Q{q_num}b",
                'marks': 15,
                'type': '15_marker',
                'topic': topic,
                'paper': 'Paper 1',
                'year': year,
                'session': session,
                'tz': tz,
                'text': part_b_match.group(1).strip()[:200],
                'pdf_path': str(pdf_path)
            })

    return questions

def parse_paper2(pdf_path, text, year, session, tz=""):
    """Parse Paper 2 - extract case studies (keep complete)."""
    case_studies = []

    # Paper 2 has case studies - keep each one complete
    # Find question numbers
    question_nums = re.findall(r'\n(\d+)\.\s+Study the following', text)

    for q_num in question_nums:
        case_studies.append({
            'question_num': f"Q{q_num}_case_study",
            'marks': 20,  # Typical Paper 2 total
            'type': 'case_study',
            'paper': 'Paper 2',
            'year': year,
            'session': session,
            'tz': tz,
            'text': f"Case study question {q_num}",
            'pdf_path': str(pdf_path)
        })

    return case_studies

def get_pdf_info(pdf_path):
    """Extract year, session, and TZ from PDF filename."""
    filename = pdf_path.stem

    # Extract year
    year_match = re.search(r'(\d{4})', filename)
    year = year_match.group(1) if year_match else "unknown"

    # Extract session
    if 'May' in filename or 'may' in filename:
        session = "May"
    elif 'November' in filename or 'november' in filename:
        session = "November"
    else:
        session = "unknown"

    # Extract TZ
    tz_match = re.search(r'TZ(\d+)', filename)
    tz = f"TZ{tz_match.group(1)}" if tz_match else ""

    return year, session, tz

def process_all_papers():
    """Process all Economics papers."""
    all_questions = {}

    # Process Paper 1
    paper1_dir = ECON_DIR / "Paper 1"
    if paper1_dir.exists():
        for pdf_path in paper1_dir.rglob("*.pdf"):
            if 'markscheme' in pdf_path.name.lower():
                continue

            print(f"Processing {pdf_path.name}...")
            text = extract_pdf_text(pdf_path)
            year, session, tz = get_pdf_info(pdf_path)

            questions = parse_paper1(pdf_path, text, year, session, tz)

            # Find corresponding markscheme
            markscheme_path = pdf_path.parent / pdf_path.name.replace('.pdf', '_markscheme.pdf')
            if not markscheme_path.exists():
                # Try alternative naming
                markscheme_path = pdf_path.parent / pdf_path.name.replace('_SL.pdf', '_SL_markscheme.pdf')

            # Extract pages as images for each question
            for q in questions:
                q_id = f"{year}_{session}_{tz}_{q['question_num']}".replace("__", "_")
                # Organize by type/topic/question_id
                topic_safe = q.get('topic', 'Unknown').replace(' ', '_')
                q_output_dir = OUTPUT_DIR / q['type'] / topic_safe / q_id

                # Extract PDF as images (question)
                if extract_pdf_pages_as_images(Path(q['pdf_path']), q_output_dir, "page"):
                    # Find all generated images
                    images = sorted(q_output_dir.glob("page-*.png"))

                    q['path'] = str(q_output_dir)
                    q['images'] = [img.name for img in images]

                    # Also extract markscheme if it exists
                    if markscheme_path.exists():
                        extract_pdf_pages_as_images(markscheme_path, q_output_dir, "answer")
                        answer_images = sorted(q_output_dir.glob("answer-*.png"))
                        q['answer_images'] = [img.name for img in answer_images]

                    del q['pdf_path']  # Remove pdf_path from final output

                    all_questions[q_id] = q

    # Process Paper 2 (case studies)
    paper2_dir = ECON_DIR / "Paper 2"
    if paper2_dir.exists():
        for pdf_path in paper2_dir.rglob("*.pdf"):
            if 'markscheme' in pdf_path.name.lower():
                continue

            print(f"Processing {pdf_path.name}...")
            text = extract_pdf_text(pdf_path)
            year, session, tz = get_pdf_info(pdf_path)

            case_studies = parse_paper2(pdf_path, text, year, session, tz)

            # Find corresponding markscheme
            markscheme_path = pdf_path.parent / pdf_path.name.replace('.pdf', '_markscheme.pdf')
            if not markscheme_path.exists():
                # Try alternative naming
                markscheme_path = pdf_path.parent / pdf_path.name.replace('_SL.pdf', '_SL_markscheme.pdf')

            # For case studies, keep the entire paper together
            for cs in case_studies:
                cs_id = f"{year}_{session}_{tz}_{cs['question_num']}".replace("__", "_")
                cs_output_dir = OUTPUT_DIR / "case_studies" / cs_id

                # Extract entire PDF as images
                if extract_pdf_pages_as_images(Path(cs['pdf_path']), cs_output_dir, "page"):
                    images = sorted(cs_output_dir.glob("page-*.png"))

                    cs['path'] = str(cs_output_dir)
                    cs['images'] = [img.name for img in images]

                    # Also extract markscheme if it exists
                    if markscheme_path.exists():
                        extract_pdf_pages_as_images(markscheme_path, cs_output_dir, "answer")
                        answer_images = sorted(cs_output_dir.glob("answer-*.png"))
                        cs['answer_images'] = [img.name for img in answer_images]

                    del cs['pdf_path']  # Remove pdf_path from final output

                    all_questions[cs_id] = cs

    # Save results
    with open(RESULTS_FILE, 'w') as f:
        json.dump(all_questions, f, indent=2)

    print(f"\nProcessed {len(all_questions)} questions")
    print(f"Results saved to {RESULTS_FILE}")

    # Print summary
    types = defaultdict(int)
    for q in all_questions.values():
        types[q['type']] += 1

    print("\nSummary:")
    for qtype, count in sorted(types.items()):
        print(f"  {qtype}: {count}")

if __name__ == "__main__":
    process_all_papers()
