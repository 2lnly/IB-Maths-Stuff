"""
Economics SL Paper Organizer V2
Extracts complete questions with text, not images
Paper 1: 4 questions per exam (Q1-Q2 Micro, Q3-Q4 Macro), each with parts (a) and (b)
Paper 2: 2 case study questions per exam
"""

import json
import re
import subprocess
from pathlib import Path
from collections import defaultdict

# Paths
ECON_DIR = Path(__file__).parent.parent / "Economics SL"
RESULTS_FILE = Path(__file__).parent / "economics_classification_results.json"

def extract_pdf_text(pdf_path):
    """Extract text from PDF using pdftotext."""
    try:
        result = subprocess.run(
            ['pdftotext', '-layout', str(pdf_path), '-'],
            capture_output=True,
            text=True,
            timeout=30
        )
        return result.stdout
    except Exception as e:
        print(f"Error extracting text from {pdf_path}: {e}")
        return ""

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

def extract_paper1_questions(text, year, session, tz):
    """
    Extract Paper 1 questions. Each paper has 4 questions.
    Q1-Q2 are typically Microeconomics (Section A)
    Q3-Q4 are typically Macroeconomics (Section B)
    Each question has parts (a) [10 marks] and (b) [15 marks]
    """
    questions = []

    # Detect sections
    has_micro = 'Microeconomics' in text or 'MICROECONOMICS' in text
    has_macro = 'Macroeconomics' in text or 'MACROECONOMICS' in text

    # Split by question numbers
    parts = re.split(r'\n(\d+)\.\s+', text)

    for i in range(1, len(parts), 2):
        if i + 1 >= len(parts):
            break

        q_num = parts[i]
        q_content = parts[i + 1]

        # Determine topic based on question number
        if q_num in ['1', '2']:
            topic = 'Microeconomics'
        elif q_num in ['3', '4']:
            topic = 'Macroeconomics'
        else:
            continue

        # Extract parts (a) and (b)
        part_a = ""
        part_b = ""

        a_match = re.search(r'\(a\)\s+(.*?)(?=\(b\)|$)', q_content, re.DOTALL)
        b_match = re.search(r'\(b\)\s+(.*?)(?=\n\d+\.|$)', q_content, re.DOTALL)

        if a_match:
            part_a = a_match.group(1).strip()
        if b_match:
            part_b = b_match.group(1).strip()

        # Clean up the text
        part_a = re.sub(r'\[10\]|\[15\]', '', part_a).strip()
        part_b = re.sub(r'\[10\]|\[15\]', '', part_b).strip()

        if part_a or part_b:
            questions.append({
                'question_num': f"Q{q_num}",
                'paper': 'Paper 1',
                'topic': topic,
                'year': year,
                'session': session,
                'tz': tz,
                'part_a': part_a,
                'part_b': part_b,
                'full_text': f"(a) [10 marks]\n{part_a}\n\n(b) [15 marks]\n{part_b}"
            })

    return questions

def extract_paper2_questions(text, year, session, tz):
    """
    Extract Paper 2 case study questions.
    Each paper typically has 2 questions with case studies.
    """
    questions = []

    # Find case study questions
    case_studies = re.finditer(
        r'(\d+)\.\s+Study the following extract.*?and answer the questions that follow\.(.*?)(?=\d+\.\s+Study the following|$)',
        text,
        re.DOTALL
    )

    for match in case_studies:
        q_num = match.group(1)
        content = match.group(2)

        questions.append({
            'question_num': f"Q{q_num}",
            'paper': 'Paper 2',
            'topic': 'Case Study',
            'year': year,
            'session': session,
            'tz': tz,
            'full_text': content.strip()
        })

    return questions

def extract_markscheme_text(ms_path, question_num):
    """Extract relevant markscheme text for a specific question."""
    if not ms_path.exists():
        return ""

    text = extract_pdf_text(ms_path)

    # For Paper 1, markschemes have format:
    # 1. (a) Question text [10 marks]
    #    Marking points...
    #    (b) Question text [15 marks]
    #    Marking points...
    # 2. (a) ...

    # Find the section starting with this question number
    # Pattern: number followed by period and space at start of line
    pattern = rf'^{question_num}\.\s+(.*?)(?=^\d+\.\s+|\Z)'
    match = re.search(pattern, text, re.MULTILINE | re.DOTALL)

    if match:
        content = match.group(1).strip()
        # Clean up excessive whitespace while preserving structure
        content = re.sub(r'\n\s*\n\s*\n+', '\n\n', content)
        return content

    # If no match, return empty
    return ""

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

            questions = extract_paper1_questions(text, year, session, tz)

            # Find markscheme
            ms_path = pdf_path.parent / pdf_path.name.replace('.pdf', '_markscheme.pdf')
            if not ms_path.exists():
                ms_path = pdf_path.parent / pdf_path.name.replace('_SL.pdf', '_SL_markscheme.pdf')

            for q in questions:
                q_id = f"{year}_{session}_{tz}_{q['question_num']}".replace("__", "_")

                # Extract markscheme for this question
                if ms_path.exists():
                    q['markscheme'] = extract_markscheme_text(ms_path, q['question_num'].replace('Q', ''))
                else:
                    q['markscheme'] = ""

                all_questions[q_id] = q

    # Process Paper 2
    paper2_dir = ECON_DIR / "Paper 2"
    if paper2_dir.exists():
        for pdf_path in paper2_dir.rglob("*.pdf"):
            if 'markscheme' in pdf_path.name.lower():
                continue

            print(f"Processing {pdf_path.name}...")
            text = extract_pdf_text(pdf_path)
            year, session, tz = get_pdf_info(pdf_path)

            questions = extract_paper2_questions(text, year, session, tz)

            # Find markscheme
            ms_path = pdf_path.parent / pdf_path.name.replace('.pdf', '_markscheme.pdf')
            if not ms_path.exists():
                ms_path = pdf_path.parent / pdf_path.name.replace('_SL.pdf', '_SL_markscheme.pdf')

            for q in questions:
                q_id = f"{year}_{session}_{tz}_{q['question_num']}".replace("__", "_")

                # Extract markscheme for this question
                if ms_path.exists():
                    q['markscheme'] = extract_markscheme_text(ms_path, q['question_num'].replace('Q', ''))
                else:
                    q['markscheme'] = ""

                all_questions[q_id] = q

    # Save results
    with open(RESULTS_FILE, 'w') as f:
        json.dump(all_questions, f, indent=2)

    print(f"\nProcessed {len(all_questions)} questions")
    print(f"Results saved to {RESULTS_FILE}")

    # Print summary
    by_paper = defaultdict(int)
    by_topic = defaultdict(int)
    for q in all_questions.values():
        by_paper[q['paper']] += 1
        by_topic[q['topic']] += 1

    print("\nBy Paper:")
    for paper, count in sorted(by_paper.items()):
        print(f"  {paper}: {count} questions")

    print("\nBy Topic:")
    for topic, count in sorted(by_topic.items()):
        print(f"  {topic}: {count} questions")

if __name__ == "__main__":
    process_all_papers()
