#!/usr/bin/env python3
"""
Migration script for Physics folders.
Renames folders from Q34_2015_May_TZ1 to Q34_TZ1_2015_fusion format.
"""

import json
import os
import shutil
import argparse
from pathlib import Path
import re

# Topic abbreviation mapping based on IB codes
SUBTOPIC_ABBREV = {
    # A: Space, Time & Motion
    "A.1": "kinematics",
    "A.2": "forces",
    "A.3": "work",
    "A.4": "momentum",
    "A.5": "relativity",

    # B: The Particulate Nature of Matter
    "B.1": "thermal",
    "B.2": "greenhouse",
    "B.3": "gas",
    "B.4": "thermo",
    "B.5": "current",

    # C: Wave Behaviour
    "C.1": "shm",
    "C.2": "wave",
    "C.3": "phenomena",
    "C.4": "standing",
    "C.5": "doppler",

    # D: Fields
    "D.1": "grav",
    "D.2": "electric",
    "D.3": "mag",
    "D.4": "induction",

    # E: Nuclear & Quantum Physics
    "E.1": "structure",
    "E.2": "quantum",
    "E.3": "radioactive",
    "E.4": "fission",
    "E.5": "fusion",

    # N/A
    "N/A": "other",
}

def parse_folder_name(folder_name):
    """
    Parse existing physics folder name to extract components.
    Examples:
      Q34_2015_May_TZ1 -> (Q34, 2015, May, TZ1)
      Q3_2011_November -> (Q3, 2011, November, None)
    """
    parts = folder_name.split('_')

    # Question number (Q34, Q3, etc.)
    question_num = parts[0]

    # Year
    year = parts[1] if len(parts) > 1 else None

    # Session (May/November)
    session = parts[2] if len(parts) > 2 else None

    # TZ (TZ1, TZ2, or None for November)
    if len(parts) > 3:
        # Could be TZ1, TZ2, or P1A_TZ1, etc.
        tz_part = parts[3]
        if tz_part.startswith('TZ'):
            tz = tz_part
        elif len(parts) > 4 and parts[4].startswith('TZ'):
            tz = parts[4]
        else:
            tz = None
    else:
        tz = None

    return question_num, year, session, tz

def get_topic_abbrev(subtopic_code):
    """Get abbreviated topic name from subtopic code."""
    if subtopic_code in SUBTOPIC_ABBREV:
        return SUBTOPIC_ABBREV[subtopic_code]

    # Fallback: use topic code letter
    if subtopic_code and '.' in subtopic_code:
        topic_code = subtopic_code.split('.')[0]
        return f"topic{topic_code}".lower()

    return "unknown"

def migrate_physics_folders(dry_run=True):
    """Migrate all physics folders to new naming convention."""

    base_dir = Path('/home/xiaohe/stuff/claudable')
    json_path = base_dir / 'data' / 'physics_classification_results.json'

    # Load JSON data
    with open(json_path, 'r') as f:
        data = json.load(f)

    print(f"{'='*60}")
    print(f"Physics Folders Migration ({'DRY RUN' if dry_run else 'LIVE'})")
    print(f"{'='*60}\n")

    renames = []
    json_updates = []
    errors = []

    # Iterate through all questions
    for question_id, question_data in data.items():
        old_path = Path(question_data['path'])

        if not old_path.exists():
            errors.append(f"Path does not exist: {old_path}")
            continue

        # Parse existing folder name
        folder_name = old_path.name
        question_num, year, session, tz = parse_folder_name(folder_name)

        if not year:
            errors.append(f"Could not extract year from {folder_name}")
            continue

        # Get topic abbreviation from JSON
        subtopic_code = question_data.get('subtopic_code', 'N/A')
        topic_abbrev = get_topic_abbrev(subtopic_code)

        # Build new folder name: Q34_TZ1_2015_fusion
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
            renames.append((old_path, new_path))
            json_updates.append((question_id, str(new_path)))

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
    log_path = base_dir / 'migration' / 'physics_migration_log.txt'
    with open(log_path, 'w') as f:
        f.write(f"Physics Migration Log\n")
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
    parser = argparse.ArgumentParser(description='Migrate physics folders')
    parser.add_argument('--execute', action='store_true',
                       help='Execute migration (default is dry-run)')
    args = parser.parse_args()

    success = migrate_physics_folders(dry_run=not args.execute)
    exit(0 if success else 1)
