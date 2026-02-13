#!/usr/bin/env python3
"""
Migration script for Math practice folders.
Renames folders from Q176 to Q176_TZ1_2012_sequences format.
"""

import json
import os
import shutil
import argparse
from pathlib import Path
import re

# Topic abbreviation mapping
TOPIC_ABBREV = {
    "calculus": "calc",
    "differentiation_basics": "diff",
    "integration_basics": "integ",
    "sequences_series": "sequences",
    "number_algebra": "algebra",
    "geometry_trigonometry": "geom",
    "triangle_geometry": "trig",
    "vectors": "vectors",
    "probability_statistics": "probstat",
    "statistics_probability": "stats",
    "combinatorics": "combin",
    "functions": "functions",
    "proof_induction": "proof",
    # Add more as needed
}

def parse_source_info(source_info_path):
    """Parse source_info.txt to extract year and session (TZ)."""
    if not os.path.exists(source_info_path):
        return None, None

    with open(source_info_path, 'r') as f:
        content = f.read()

    # Extract year
    year_match = re.search(r'Year:\s*(\d{4})', content)
    year = year_match.group(1) if year_match else None

    # Extract TZ from session (e.g., "May_TZ1" -> "TZ1", "May" -> None)
    session_match = re.search(r'Session:\s*([^_\s]+)(_TZ\d+)?', content)
    if session_match:
        tz = session_match.group(2).replace('_', '') if session_match.group(2) else None
    else:
        tz = None

    return year, tz

def get_topic_abbrev(subtopic):
    """Get abbreviated topic name."""
    # Try to find in mapping
    if subtopic in TOPIC_ABBREV:
        return TOPIC_ABBREV[subtopic]

    # Otherwise use first part of subtopic (e.g., "sequences_series" -> "sequences")
    parts = subtopic.split('_')
    if len(parts) > 1:
        return parts[0][:8]  # Max 8 chars
    return subtopic[:8]

def migrate_math_folders(dry_run=True):
    """Migrate all math practice folders to new naming convention."""

    base_dir = Path('/home/xiaohe/stuff/claudable')
    json_path = base_dir / 'data' / 'practice_classification_results.json'

    # Load JSON data
    with open(json_path, 'r') as f:
        data = json.load(f)

    print(f"{'='*60}")
    print(f"Math Folders Migration ({'DRY RUN' if dry_run else 'LIVE'})")
    print(f"{'='*60}\n")

    renames = []
    json_updates = []
    errors = []

    # Iterate through all questions
    for question_id, question_data in data.items():
        old_path = base_dir / question_data['path']

        if not old_path.exists():
            errors.append(f"Path does not exist: {old_path}")
            continue

        # Parse source_info.txt
        source_info_path = old_path / 'source_info.txt'
        year, tz = parse_source_info(source_info_path)

        if not year:
            errors.append(f"Could not extract year from {source_info_path}")
            continue

        # Get topic abbreviation
        subtopic = question_data.get('primary_subtopic', 'unknown')
        topic_abbrev = get_topic_abbrev(subtopic)

        # Build new folder name
        question_num = question_data['question_num']  # e.g., "Q176"
        tz_part = f"_{tz}" if tz else ""
        new_folder_name = f"{question_num}{tz_part}_{year}_{topic_abbrev}"

        # Build new path
        new_path = old_path.parent / new_folder_name

        # Check for duplicates
        if new_path.exists() and new_path != old_path:
            # Add suffix
            suffix = 2
            while new_path.exists():
                new_folder_name_with_suffix = f"{new_folder_name}_{suffix}"
                new_path = old_path.parent / new_folder_name_with_suffix
                suffix += 1

        # Record rename
        if old_path != new_path:
            relative_new_path = new_path.relative_to(base_dir)
            renames.append((old_path, new_path))
            json_updates.append((question_id, str(relative_new_path)))

    # Print summary
    print(f"Total questions: {len(data)}")
    print(f"Folders to rename: {len(renames)}")
    print(f"Errors: {len(errors)}\n")

    if errors:
        print("Errors encountered:")
        for error in errors[:10]:  # Show first 10
            print(f"  - {error}")
        if len(errors) > 10:
            print(f"  ... and {len(errors) - 10} more errors")
        print()

    # Show sample renames
    print("Sample renames (first 10):")
    for old, new in renames[:10]:
        print(f"  {old.name} → {new.name}")
    if len(renames) > 10:
        print(f"  ... and {len(renames) - 10} more renames")
    print()

    if dry_run:
        print("DRY RUN: No changes made. Run with --execute to apply changes.")
        return True

    # Execute renames
    print("Executing renames...")
    for i, (old, new) in enumerate(renames, 1):
        try:
            shutil.move(str(old), str(new))
            if i % 100 == 0:
                print(f"  Renamed {i}/{len(renames)} folders...")
        except Exception as e:
            errors.append(f"Failed to rename {old} to {new}: {e}")

    print(f"Renamed {len(renames)} folders.\n")

    # Update JSON
    print("Updating JSON paths...")
    for question_id, new_path in json_updates:
        data[question_id]['path'] = new_path

    # Write updated JSON
    with open(json_path, 'w') as f:
        json.dump(data, f, indent=2)

    print(f"Updated {len(json_updates)} paths in JSON.")

    # Write log
    log_path = base_dir / 'migration' / 'math_migration_log.txt'
    with open(log_path, 'w') as f:
        f.write(f"Math Migration Log\n")
        f.write(f"{'='*60}\n\n")
        f.write(f"Total folders renamed: {len(renames)}\n")
        f.write(f"Total JSON paths updated: {len(json_updates)}\n")
        f.write(f"Total errors: {len(errors)}\n\n")
        if errors:
            f.write("Errors:\n")
            for error in errors:
                f.write(f"  - {error}\n")

    print(f"\nMigration complete! Log saved to {log_path}")
    return len(errors) == 0

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Migrate math practice folders')
    parser.add_argument('--execute', action='store_true',
                       help='Execute migration (default is dry-run)')
    args = parser.parse_args()

    success = migrate_math_folders(dry_run=not args.execute)
    exit(0 if success else 1)
