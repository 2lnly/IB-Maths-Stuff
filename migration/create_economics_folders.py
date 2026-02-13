#!/usr/bin/env python3
"""
Migration script for Economics - creates folder structure for the first time.
Economics currently has no folders, all data is in JSON.
"""

import json
import os
import argparse
from pathlib import Path
import re

# Topic abbreviation mapping
TOPIC_ABBREV = {
    "Microeconomics": "micro",
    "Macroeconomics": "macro",
    "Case Study": "case",
    "International Economics": "intl",
    "Development Economics": "dev",
}

def is_15_marker(question_text):
    """Check if a question is a 15-marker based on text content."""
    if not question_text:
        return False
    return '[15 marks]' in question_text or '[15]' in question_text

def create_economics_folders(dry_run=True):
    """Create folder structure for economics questions."""

    base_dir = Path('/home/xiaohe/stuff/claudable')
    json_path = base_dir / 'data' / 'economics_classification_results.json'
    economics_dir = base_dir / 'economics'

    # Load JSON data
    with open(json_path, 'r') as f:
        data = json.load(f)

    print(f"{'='*60}")
    print(f"Economics Folders Creation ({'DRY RUN' if dry_run else 'LIVE'})")
    print(f"{'='*60}\n")

    folders_to_create = []
    json_updates = []
    errors = []
    fifteen_marker_count = 0

    # Iterate through all questions
    for question_id, question_data in data.items():
        # Extract metadata
        question_num = question_data.get('question_num', question_id)
        paper = question_data.get('paper', 'Paper 1')
        topic = question_data.get('topic', 'Unknown')
        year = question_data.get('year')
        session = question_data.get('session')
        tz = question_data.get('tz')

        if not year:
            errors.append(f"Missing year for {question_id}")
            continue

        # Get topic abbreviation
        topic_abbrev = TOPIC_ABBREV.get(topic, topic[:8].lower())

        # Build folder name: Q1_TZ1_2019_micro
        tz_part = f"_{tz}" if tz else ""
        folder_name = f"{question_num}{tz_part}_{year}_{topic_abbrev}"

        # Build full path
        paper_folder = paper.replace(' ', '_')
        folder_path = economics_dir / paper_folder / folder_name

        # Check if it's a 15-marker
        part_b = question_data.get('part_b', '')
        is_15 = is_15_marker(part_b)
        if is_15:
            fifteen_marker_count += 1

        # Prepare files to create
        files_to_create = {}

        # Create question files
        if 'part_a' in question_data and question_data['part_a']:
            files_to_create['question_part_a.txt'] = question_data['part_a']

        if 'part_b' in question_data and question_data['part_b']:
            files_to_create['question_part_b.txt'] = question_data['part_b']

        if 'full_text' in question_data and question_data['full_text']:
            files_to_create['question_full.txt'] = question_data['full_text']

        if 'markscheme' in question_data and question_data['markscheme']:
            files_to_create['markscheme.txt'] = question_data['markscheme']

        # Record folder creation
        relative_path = folder_path.relative_to(base_dir)
        folders_to_create.append((folder_path, files_to_create))
        json_updates.append((question_id, str(relative_path), is_15))

    # Print summary
    print(f"Total questions: {len(data)}")
    print(f"Folders to create: {len(folders_to_create)}")
    print(f"15-marker questions: {fifteen_marker_count}")
    print(f"Errors: {len(errors)}\n")

    if errors:
        print("Errors encountered:")
        for error in errors[:10]:  # Show first 10
            print(f"  - {error}")
        if len(errors) > 10:
            print(f"  ... and {len(errors) - 10} more errors")
        print()

    # Show sample folders
    print("Sample folders (first 10):")
    for folder_path, files in folders_to_create[:10]:
        file_list = ', '.join(files.keys())
        print(f"  {folder_path.relative_to(base_dir)} → [{file_list}]")
    if len(folders_to_create) > 10:
        print(f"  ... and {len(folders_to_create) - 10} more folders")
    print()

    if dry_run:
        print("DRY RUN: No changes made. Run with --execute to apply changes.")
        return True

    # Create folders and files
    print("Creating folders and files...")
    for i, (folder_path, files) in enumerate(folders_to_create, 1):
        try:
            # Create folder
            folder_path.mkdir(parents=True, exist_ok=True)

            # Write files
            for filename, content in files.items():
                file_path = folder_path / filename
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(content)

            if i % 20 == 0:
                print(f"  Created {i}/{len(folders_to_create)} folders...")
        except Exception as e:
            errors.append(f"Failed to create {folder_path}: {e}")

    print(f"Created {len(folders_to_create)} folders.\n")

    # Update JSON
    print("Updating JSON with paths and 15-marker flags...")
    for question_id, path, is_15 in json_updates:
        data[question_id]['path'] = path
        data[question_id]['is_15_marker'] = is_15
        # Normalize field names
        if 'topic' in data[question_id]:
            data[question_id]['primary_topic'] = data[question_id]['topic']
        # Economics doesn't have subtopics, use topic as subtopic
        data[question_id]['primary_subtopic'] = data[question_id].get('primary_topic', data[question_id].get('topic', 'Unknown'))
        # Add display mode
        data[question_id]['display_mode'] = 'text'

    # Write updated JSON
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"Updated {len(json_updates)} entries in JSON.")

    # Write log
    log_path = base_dir / 'migration' / 'economics_migration_log.txt'
    with open(log_path, 'w') as f:
        f.write(f"Economics Migration Log\n")
        f.write(f"{'='*60}\n\n")
        f.write(f"Total folders created: {len(folders_to_create)}\n")
        f.write(f"15-marker questions: {fifteen_marker_count}\n")
        f.write(f"Total JSON entries updated: {len(json_updates)}\n")
        f.write(f"Total errors: {len(errors)}\n\n")
        if errors:
            f.write("Errors:\n")
            for error in errors:
                f.write(f"  - {error}\n")

    print(f"\nMigration complete! Log saved to {log_path}")
    return len(errors) == 0

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Create economics folder structure')
    parser.add_argument('--execute', action='store_true',
                       help='Execute migration (default is dry-run)')
    args = parser.parse_args()

    success = create_economics_folders(dry_run=not args.execute)
    exit(0 if success else 1)
