#!/usr/bin/env python3
"""
Catalog all IB Math HL PDFs across Paper 1, Paper 2, Paper 3 directories.
Produces data/pdf_catalog.json with metadata for every question paper + markscheme pair.
"""

import json
import os
import re
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Paper 3 subject option names as they appear in filenames
P3_OPTIONS = [
    "Calculus",
    "Discrete_mathematics",
    "Series_and_differential_equations",
    "Sets_relations_and_groups",
    "Statistics_and_probability",
]


def parse_session_folder(folder_name):
    """Parse a session folder name like '2012 May TZ1' into (year, session, tz)."""
    match = re.match(r"(\d{4})\s+(May|November)(?:\s+(TZ\d))?$", folder_name)
    if not match:
        return None
    return {
        "year": int(match.group(1)),
        "session": match.group(2),
        "tz": match.group(3),  # None if no TZ
    }


def find_paper_pairs(session_dir, paper_num):
    """Find question paper + markscheme pairs in a session directory.

    Returns list of dicts with: pdf_path, markscheme_path, paper3_option
    """
    files = os.listdir(session_dir)
    pairs = []

    # Separate markschemes from question papers
    markschemes = [f for f in files if f.endswith(".pdf") and "markscheme" in f.lower()]
    questions = [f for f in files if f.endswith(".pdf") and "markscheme" not in f.lower()]

    for q_file in questions:
        # Strip download duplicates like " (1)" from filename for matching
        q_clean = re.sub(r"\s*\(\d+\)", "", q_file)

        # Find matching markscheme
        expected_ms = q_clean.replace(".pdf", "_markscheme.pdf")
        if expected_ms not in markschemes:
            # Try case-insensitive match
            expected_ms = None
            q_base = q_clean.replace(".pdf", "").lower()
            for ms in markschemes:
                ms_base = ms.replace("_markscheme.pdf", "").lower()
                if ms_base == q_base:
                    expected_ms = ms
                    break

        # Detect Paper 3 subject option from filename
        paper3_option = None
        if paper_num == 3:
            for opt in P3_OPTIONS:
                if opt.lower() in q_file.lower().replace(" ", "_"):
                    paper3_option = opt
                    break

        pairs.append({
            "pdf_path": os.path.join(session_dir, q_file),
            "markscheme_path": os.path.join(session_dir, expected_ms) if expected_ms else None,
            "paper3_option": paper3_option,
        })

    return pairs


def catalog_paper(paper_num):
    """Catalog all PDFs for a given paper number."""
    paper_dir = os.path.join(BASE_DIR, f"Paper {paper_num}")
    if not os.path.isdir(paper_dir):
        print(f"Warning: {paper_dir} does not exist")
        return []

    entries = []

    for year_folder in sorted(os.listdir(paper_dir)):
        year_path = os.path.join(paper_dir, year_folder)
        if not os.path.isdir(year_path):
            continue

        for session_folder in sorted(os.listdir(year_path)):
            session_path = os.path.join(year_path, session_folder)
            if not os.path.isdir(session_path):
                continue

            parsed = parse_session_folder(session_folder)
            if not parsed:
                print(f"Warning: Could not parse session folder: {session_folder}")
                continue

            year = parsed["year"]
            curriculum = "AA" if year >= 2021 else "pre-2021"

            pairs = find_paper_pairs(session_path, paper_num)

            for pair in pairs:
                # Make paths relative to BASE_DIR
                rel_pdf = os.path.relpath(pair["pdf_path"], BASE_DIR)
                rel_ms = os.path.relpath(pair["markscheme_path"], BASE_DIR) if pair["markscheme_path"] else None

                entries.append({
                    "paper": f"Paper {paper_num}",
                    "year": year,
                    "session": parsed["session"],
                    "tz": parsed["tz"],
                    "curriculum": curriculum,
                    "pdf_path": rel_pdf,
                    "markscheme_path": rel_ms,
                    "paper3_option": pair["paper3_option"],
                })

    return entries


def validate_catalog(catalog):
    """Check for issues in the catalog."""
    issues = []
    for entry in catalog:
        if not entry["markscheme_path"]:
            issues.append(f"Missing markscheme: {entry['pdf_path']}")
        elif not os.path.exists(os.path.join(BASE_DIR, entry["markscheme_path"])):
            issues.append(f"Markscheme file not found: {entry['markscheme_path']}")
        if not os.path.exists(os.path.join(BASE_DIR, entry["pdf_path"])):
            issues.append(f"Question PDF not found: {entry['pdf_path']}")
    return issues


def print_summary(catalog):
    """Print summary statistics."""
    from collections import Counter

    paper_counts = Counter(e["paper"] for e in catalog)
    year_range = (min(e["year"] for e in catalog), max(e["year"] for e in catalog))
    missing_ms = sum(1 for e in catalog if not e["markscheme_path"])
    p3_options = Counter(e["paper3_option"] for e in catalog if e["paper3_option"])

    print(f"\n=== PDF Catalog Summary ===")
    print(f"Total question papers: {len(catalog)}")
    for paper, count in sorted(paper_counts.items()):
        print(f"  {paper}: {count}")
    print(f"Year range: {year_range[0]}-{year_range[1]}")
    print(f"Missing markschemes: {missing_ms}")
    if p3_options:
        print(f"Paper 3 options:")
        for opt, count in sorted(p3_options.items()):
            print(f"  {opt}: {count}")


def main():
    catalog = []
    for paper_num in [1, 2, 3]:
        entries = catalog_paper(paper_num)
        catalog.extend(entries)
        print(f"Paper {paper_num}: {len(entries)} question papers found")

    issues = validate_catalog(catalog)
    if issues:
        print(f"\n=== Issues Found ({len(issues)}) ===")
        for issue in issues:
            print(f"  - {issue}")

    print_summary(catalog)

    # Save catalog
    output_path = os.path.join(BASE_DIR, "data", "pdf_catalog.json")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(catalog, f, indent=2)
    print(f"\nCatalog saved to {output_path}")


if __name__ == "__main__":
    main()
