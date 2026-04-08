#!/usr/bin/env python3
"""
Catalog all IB Physics HL PDFs across Paper 1, Paper 2, Paper 3 directories.
Produces data/physics_pdf_catalog.json with metadata for every question paper + markscheme pair.

Physics HL folder structure:
  Physics HL/Paper 1/<session_folder>/...
  Physics HL/Paper 2/<session_folder>/...
  Physics HL/Paper 3/<session_folder>/...

Session folder naming pattern (underscores, not spaces):
  2010_May_Physics_TZ1
  2010_November_Physics
  2023_November_Physics__TZ1   (double underscore)
  2025_May_Physics_paper_1B_TZ1
"""

import json
import os
import re
import sys
from collections import Counter

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def parse_session_folder(folder_name):
    """Parse a session folder name into (year, session, tz).

    Handles patterns like:
      2010_May_Physics_TZ1
      2010_November_Physics
      2023_November_Physics__TZ1   (double underscore before TZ)
      2025_May_Physics_paper_1B_TZ1
    """
    # Regex: year, session, then optionally: underscores, optional 'paper_\w+_', then TZ
    match = re.match(
        r'^(\d{4})_(May|November)_Physics(?:_+(?:paper_\w+_)?(?:(TZ\d)))?',
        folder_name
    )
    if not match:
        return None
    return {
        "year": int(match.group(1)),
        "session": match.group(2),
        "tz": match.group(3),  # None if no TZ
    }


def find_paper_pairs(session_dir):
    """Find question paper + markscheme pairs in a session directory.

    Returns list of dicts with: pdf_path, markscheme_path
    """
    try:
        files = os.listdir(session_dir)
    except OSError:
        return []

    pairs = []

    # Separate markschemes from question papers
    markschemes = [f for f in files if f.endswith(".pdf") and "markscheme" in f.lower()]
    questions = [f for f in files if f.endswith(".pdf") and "markscheme" not in f.lower()]

    for q_file in questions:
        # Strip download duplicates like " (1)" from filename for matching
        q_clean = re.sub(r"\s*\(\d+\)", "", q_file)

        # Find matching markscheme: question base + _markscheme.pdf
        expected_ms = q_clean.replace(".pdf", "_markscheme.pdf")

        if expected_ms in markschemes:
            matched_ms = expected_ms
        else:
            # Try case-insensitive match
            matched_ms = None
            q_base = q_clean.replace(".pdf", "").lower()
            for ms in markschemes:
                ms_base = ms.replace("_markscheme.pdf", "").lower()
                if ms_base == q_base:
                    matched_ms = ms
                    break

        pairs.append({
            "pdf_path": os.path.join(session_dir, q_file),
            "markscheme_path": os.path.join(session_dir, matched_ms) if matched_ms else None,
        })

    return pairs


def catalog_paper(paper_num):
    """Catalog all PDFs for a given paper number."""
    paper_dir = os.path.join(BASE_DIR, "Physics HL", f"Paper {paper_num}")
    if not os.path.isdir(paper_dir):
        print(f"Warning: {paper_dir} does not exist")
        return []

    entries = []

    for session_folder in sorted(os.listdir(paper_dir)):
        session_path = os.path.join(paper_dir, session_folder)
        if not os.path.isdir(session_path):
            continue

        parsed = parse_session_folder(session_folder)
        if not parsed:
            print(f"Warning: Could not parse session folder: {session_folder}")
            continue

        year = parsed["year"]
        curriculum = "new" if year >= 2023 else "pre-2023"

        pairs = find_paper_pairs(session_path)

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
    paper_counts = Counter(e["paper"] for e in catalog)
    if not catalog:
        print("\n=== PDF Catalog Summary ===")
        print("No entries found.")
        return

    year_range = (min(e["year"] for e in catalog), max(e["year"] for e in catalog))
    missing_ms = sum(1 for e in catalog if not e["markscheme_path"])
    curriculum_counts = Counter(e["curriculum"] for e in catalog)

    print(f"\n=== Physics PDF Catalog Summary ===")
    print(f"Total question papers: {len(catalog)}")
    for paper, count in sorted(paper_counts.items()):
        print(f"  {paper}: {count}")
    print(f"Year range: {year_range[0]}-{year_range[1]}")
    print(f"Missing markschemes: {missing_ms}")
    print(f"Curriculum breakdown:")
    for cur, count in sorted(curriculum_counts.items()):
        print(f"  {cur}: {count}")


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
    output_path = os.path.join(BASE_DIR, "data", "physics_pdf_catalog.json")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(catalog, f, indent=2)
    print(f"\nCatalog saved to {output_path}")


if __name__ == "__main__":
    main()
