#!/usr/bin/env python3
"""
Classify all extracted IB Math questions using Claude Haiku.

For each question, sends the image to Claude Haiku and gets:
- topic_code (1-5 or P3-C/D/S/SP)
- subtopic_code (e.g. "1.4")
- subtopic_name
- description (one line)
- difficulty (1-5)

Output: data/question_bank.json

Run with ANTHROPIC_API_KEY set in environment.
Checkpoints every 50 questions so it can be resumed safely.
"""

import anthropic
import base64
import json
import os
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
PRACTICE_DIR = BASE_DIR / "practice_new"
OUTPUT_PATH = BASE_DIR / "data" / "question_bank.json"
CHECKPOINT_PATH = BASE_DIR / "data" / "classification_checkpoint.json"

# IB Math AA HL taxonomy
TAXONOMY = """
IB Math Analysis & Approaches HL Topic Taxonomy:

Topic 1: Number & Algebra
  1.1   Partial Fractions, Indices & Standard Form
  1.2   Exponentials & Logs
  1.3   Sequences & Series (arithmetic, geometric, sigma notation, applications, compound interest)
  1.4   Simple Proof & Reasoning (deduction, counter-example)
  1.5   Proof by Induction & Contradiction
  1.6   Binomial Theorem (binomial coefficients, Pascal's triangle, extension)
  1.7   Permutations & Combinations (counting principles)
  1.8   Complex Numbers (intro, operations, Argand diagrams, modulus & argument)
  1.9   Further Complex Numbers (polar/Euler form, de Moivre, roots of complex numbers, complex roots of polynomials)
  1.10  Systems of Linear Equations (row reduction, number of solutions)

Topic 2: Functions
  2.1   Linear Functions & Graphs (equations of lines, parallel & perpendicular)
  2.2   Quadratic Functions & Graphs (factorising, completing the square, discriminant, inequalities)
  2.3   Functions Toolkit (composite, inverse, odd/even, periodic, self-inverse, graphing)
  2.4   Other Functions & Graphs (exponential & log, solving analytically/graphically, modelling)
  2.5   Reciprocal & Rational Functions
  2.6   Transformations of Graphs (translations, reflections, stretches, composite transformations)
  2.7   Polynomial Functions (division, factor & remainder theorem, sum & product of roots)
  2.8   Inequalities (graphical, polynomial)
  2.9   Modulus Functions & Further Transformations (modulus equations & inequalities, reciprocal & square transformations)

Topic 3: Geometry & Trigonometry
  3.1   Geometry Toolkit (coordinate geometry, arcs & sectors, radian measure)
  3.2   Geometry of 3D Shapes (3D coordinate geometry, volume & surface area)
  3.3   Trigonometry (right-angled trig, sine rule, cosine rule, area of triangle, bearings)
  3.4   The Unit Circle & Exact Values
  3.5   Trigonometric Functions & Graphs (graphs, transformations, modelling)
  3.6   Trigonometric Equations & Identities (simple identities, compound & double angle formulae, linear & quadratic trig equations)
  3.7   Inverse & Reciprocal Trigonometric Functions
  3.8   Trigonometric Proof & Equation Strategies
  3.9   Vector Properties (intro, scalar product, vector product, angle between vectors, areas)
  3.10  Vector Equations of Lines (vector/parametric/Cartesian forms, parallel/intersecting/skew, distances)
  3.11  Vector Planes (equations of planes, intersections, angles, distances)

Topic 4: Statistics & Probability
  4.1   Statistics Toolkit (sampling, measures of central tendency & dispersion, frequency tables, outliers, box plots, histograms)
  4.2   Correlation & Regression (scatter diagrams, Pearson's PMCC, linear regression)
  4.3   Probability (independent & mutually exclusive events, conditional probability, Bayes' theorem, Venn & tree diagrams)
  4.4   Discrete Random Variables (distributions, mean & variance, transformations)
  4.5   Binomial Distribution
  4.6   Normal Distribution (calculations, standardisation, z-values, unknown parameters)
  4.7   Continuous Random Variables (PDF, median, mode, mean & variance)

Topic 5: Calculus
  5.1   Differentiation (intro to derivatives, differentiating powers of x, gradients, tangents & normals, increasing/decreasing)
  5.2   Techniques & Applications of Differentiation (trig/exp/log, chain/product/quotient rule, higher order, stationary points, concavity, inflection)
  5.3   Integration (intro, powers of x, constant of integration)
  5.4   Techniques & Applications of Integration (trig/exp/reciprocal, reverse chain rule, substitution, definite integrals, area between curves)
  5.5   Optimisation (modelling with differentiation)
  5.6   Kinematics (displacement, velocity, acceleration, calculus for kinematics)
  5.7   Basic Limits & Continuity
  5.8   Further Differentiation (first principles, implicit, related rates, inverse/reciprocal trig, parametric)
  5.9   Further Integration (reciprocal & inverse trig, by parts, partial fractions, area wrt y-axis, volumes of revolution)
  5.10  Differential Equations (first order, Euler's method, separation of variables, homogeneous, integrating factor, logistic equation)
  5.11  Maclaurin Series (standard functions, composites & products, differentiating & integrating, from DEs)
  5.12  Limits using l'Hôpital's Rule & Maclaurin Series

Paper 3 Historical Options (pre-2021 only — use these for Paper 3 questions from 2006-2020):
  P3-C   Further Calculus (improper integrals, convergence, advanced differential equations)
  P3-D   Discrete Mathematics (graph theory, algorithms, recurrence relations, Diophantine equations)
  P3-S   Sets, Relations and Groups (abstract algebra, group theory, equivalence classes)
  P3-SP  Further Statistics and Probability (further distributions, estimation, regression)
"""

DIFFICULTY_GUIDE = """
Difficulty scale 1-5:
  1 = Routine recall or single-step calculation (typically 1-4 marks)
  2 = Standard application of a single technique (typically 4-6 marks)
  3 = Multi-step problem requiring two or more techniques (typically 6-8 marks)
  4 = Challenging synthesis, non-obvious approach, or extended working (typically 8-12 marks)
  5 = Extended investigation, abstract proof, or very high cognitive demand (typically 12+ marks, or all Paper 3 questions)
"""

CLASSIFICATION_PROMPT = """You are classifying an IB Mathematics Analysis & Approaches Higher Level exam question.

{taxonomy}

{difficulty}

Look at the question image and respond with ONLY a JSON object (no markdown, no code fences):
{{
  "topic_code": "1",
  "topic_name": "Number & Algebra",
  "subtopic_code": "1.3",
  "subtopic_name": "Sequences & Series",
  "description": "One-line description of what the question asks",
  "difficulty": 2,
  "marks": 6
}}

Rules:
- topic_code must be exactly "1", "2", "3", "4", "5", or for old Paper 3: "P3-C", "P3-D", "P3-S", "P3-SP"
- topic_name must exactly match the topic name in the taxonomy above
- subtopic_code must exactly match a code from the taxonomy (e.g. "1.3", "3.10", "5.11")
- subtopic_name must exactly match the subtopic name from the taxonomy
- marks: read from "[Maximum mark: N]" if visible, otherwise estimate from question length
- difficulty: 1=routine single-step, 2=standard application, 3=multi-step, 4=challenging, 5=extended/Paper3
- Choose the PRIMARY topic/subtopic even if the question touches multiple areas"""


def load_question_image(question_dir):
    """Load the first question image as base64."""
    for img_name in ["question_p1.png", "question_p2.png"]:
        img_path = question_dir / img_name
        if img_path.exists():
            with open(img_path, "rb") as f:
                return base64.standard_b64encode(f.read()).decode("utf-8")
    return None


def load_source_info(question_dir):
    """Load source_info.txt as a dict."""
    src_path = question_dir / "source_info.txt"
    info = {}
    if src_path.exists():
        with open(src_path) as f:
            for line in f:
                if ":" in line:
                    key, _, val = line.partition(":")
                    info[key.strip().lower().replace(" ", "_")] = val.strip()
    return info


def classify_question(client, question_dir, paper_num):
    """Classify a single question using Claude Haiku. Returns classification dict or None."""
    img_b64 = load_question_image(question_dir)
    if img_b64 is None:
        return None

    prompt = CLASSIFICATION_PROMPT.format(taxonomy=TAXONOMY, difficulty=DIFFICULTY_GUIDE)

    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": img_b64,
                        },
                    },
                    {"type": "text", "text": prompt},
                ],
            }],
        )

        text = response.content[0].text.strip()
        # Strip markdown code fences if present
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        text = text.strip()

        result = json.loads(text)
        return result

    except json.JSONDecodeError as e:
        print(f"    JSON parse error: {e}, response: {text[:100]}")
        return None
    except Exception as e:
        print(f"    API error: {e}")
        return None


def build_question_entry(question_id, question_dir, source_info, classification):
    """Build the final question bank entry."""
    paper_folder = question_dir.parent.name  # "paper 1"
    paper_num = int(paper_folder.split()[-1])

    # Parse session from source_info
    session_raw = source_info.get("session", "")
    if "_" in session_raw:
        parts = session_raw.split("_")
        session = parts[0]  # "May" or "November"
        tz = parts[1] if len(parts) > 1 else None
    else:
        session = session_raw
        tz = None

    year = int(source_info.get("year", 0))
    original_q = source_info.get("original_question", "Q?").lstrip("Q")
    try:
        original_q_num = int(original_q)
    except ValueError:
        original_q_num = None

    marks_from_source = source_info.get("marks")
    marks_from_classification = classification.get("marks") if classification else None

    # Prefer markscheme-extracted marks over AI estimate
    marks = None
    if marks_from_source:
        try:
            marks = int(marks_from_source)
        except ValueError:
            pass
    if marks is None and marks_from_classification:
        try:
            marks = int(marks_from_classification)
        except (ValueError, TypeError):
            pass

    has_answer = (question_dir / "answer_p1.png").exists()

    # Determine section (A = short, B = long) for Paper 1 and 2
    # Section A: typically Q1-Q10 (or Q1-15), Section B: remaining long questions
    section = None
    if paper_num in [1, 2] and original_q_num:
        if marks and marks <= 8:
            section = "A"
        elif marks and marks > 8:
            section = "B"

    paper3_option = source_info.get("paper_3_option")

    curriculum = source_info.get("curriculum", "pre-2021")

    is_scan = source_info.get("is_scan", "false").lower() == "true"

    entry = {
        "question_id": question_id,
        "paper": f"Paper{paper_num}",
        "paper_num": paper_num,
        "year": year,
        "session": session,
        "tz": tz,
        "curriculum": curriculum,
        "original_question_num": original_q_num,
        "section": section,
        "paper3_option": paper3_option,
        "marks": marks,
        "has_answer": has_answer,
        "is_scan": is_scan,
        "display_mode": "image",
        "path": str(question_dir.relative_to(BASE_DIR)),
    }

    if classification:
        entry.update({
            "topic_code": classification.get("topic_code"),
            "topic_name": classification.get("topic_name"),
            "subtopic_code": classification.get("subtopic_code"),
            "subtopic_name": classification.get("subtopic_name"),
            "description": classification.get("description"),
            "difficulty": classification.get("difficulty"),
        })
    else:
        entry.update({
            "topic_code": None,
            "topic_name": None,
            "subtopic_code": None,
            "subtopic_name": None,
            "description": None,
            "difficulty": None,
        })

    return entry


def load_checkpoint():
    """Load checkpoint of already-classified question IDs."""
    if CHECKPOINT_PATH.exists():
        with open(CHECKPOINT_PATH) as f:
            return json.load(f)
    return {}


def save_checkpoint(question_bank):
    """Save current progress."""
    with open(CHECKPOINT_PATH, "w") as f:
        json.dump(question_bank, f)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Classify IB Math questions with Claude Haiku")
    parser.add_argument("--paper", type=int, choices=[1, 2, 3], help="Only process this paper")
    parser.add_argument("--year", type=int, help="Only process this year")
    parser.add_argument("--limit", type=int, help="Process only N questions (for testing)")
    parser.add_argument("--force", action="store_true", help="Re-classify already done questions")
    parser.add_argument("--no-api", action="store_true", help="Skip API calls, just build metadata (for testing)")
    args = parser.parse_args()

    # Load existing progress
    question_bank = load_checkpoint()
    print(f"Loaded {len(question_bank)} previously classified questions")

    # Discover all question directories
    all_dirs = []
    for paper_num in [1, 2, 3]:
        if args.paper and paper_num != args.paper:
            continue
        paper_dir = PRACTICE_DIR / f"paper {paper_num}"
        if not paper_dir.exists():
            continue
        for q_dir in sorted(paper_dir.iterdir()):
            if not q_dir.is_dir():
                continue
            src = load_source_info(q_dir)
            if args.year and src.get("year") != str(args.year):
                continue
            all_dirs.append(q_dir)

    print(f"Found {len(all_dirs)} question directories")

    # Filter out already classified (unless --force)
    to_classify = []
    for q_dir in all_dirs:
        q_id = q_dir.name
        already_done = q_id in question_bank and question_bank[q_id].get('topic_code') is not None
        if not already_done or args.force:
            to_classify.append(q_dir)
        # Still add already-classified to the output
    print(f"{len(to_classify)} need classification")

    if args.limit:
        to_classify = to_classify[:args.limit]
        print(f"Limited to {len(to_classify)} questions")

    if not args.no_api and to_classify:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            print("ERROR: ANTHROPIC_API_KEY environment variable not set.")
            print("Set it with: export ANTHROPIC_API_KEY='your-key-here'")
            sys.exit(1)
        client = anthropic.Anthropic(api_key=api_key)
    else:
        client = None

    import threading
    from concurrent.futures import ThreadPoolExecutor, as_completed

    WORKERS = 50
    lock = threading.Lock()
    errors = 0
    completed = 0

    def process_one(q_dir):
        q_id = q_dir.name
        paper_num = int(q_dir.parent.name.split()[-1])
        src = load_source_info(q_dir)
        is_scan = src.get("is_scan", "false").lower() == "true"

        classification = None
        if client and not is_scan and not args.no_api:
            classification = classify_question(client, q_dir, paper_num)
        entry = build_question_entry(q_id, q_dir, src, classification)
        return q_id, entry, classification, is_scan

    futures = {}
    with ThreadPoolExecutor(max_workers=WORKERS) as executor:
        for q_dir in to_classify:
            futures[executor.submit(process_one, q_dir)] = q_dir

        for future in as_completed(futures):
            try:
                q_id, entry, classification, is_scan = future.result()
                with lock:
                    question_bank[q_id] = entry
                    completed += 1
                    if classification is None and not is_scan:
                        errors += 1
                    subtopic = classification.get('subtopic_name', '?') if classification else ('scan' if is_scan else 'FAILED')
                    diff = classification.get('difficulty', '?') if classification else ''
                    diff_str = f" (diff={diff})" if diff else ''
                    print(f"[{completed}/{len(to_classify)}] {q_id}: {subtopic}{diff_str}")
                    if completed % 100 == 0:
                        save_checkpoint(question_bank)
                        print(f"  --- Checkpoint saved ({completed} done) ---")
            except Exception as e:
                with lock:
                    errors += 1
                    completed += 1
                    print(f"ERROR {futures[future].name}: {e}")

    # Final save
    save_checkpoint(question_bank)

    # Also write the final question_bank.json (sorted)
    sorted_bank = dict(sorted(question_bank.items()))
    OUTPUT_PATH.parent.mkdir(exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(sorted_bank, f, indent=2)

    print(f"\n=== Classification Summary ===")
    print(f"Total questions: {len(question_bank)}")
    print(f"Classified: {sum(1 for e in question_bank.values() if e.get('topic_code'))}")
    print(f"Unclassified (scans): {sum(1 for e in question_bank.values() if e.get('is_scan'))}")
    print(f"Errors: {errors}")
    print(f"Saved to {OUTPUT_PATH}")

    # Topic breakdown
    from collections import Counter
    topics = Counter(e.get("topic_name") for e in question_bank.values() if e.get("topic_name"))
    print("\nTopic distribution:")
    for topic, count in sorted(topics.items(), key=lambda x: -x[1]):
        print(f"  {topic}: {count}")


if __name__ == "__main__":
    main()
