#!/usr/bin/env python3
"""
Normalization script for all JSON files.
Ensures consistent field names across math, physics, and economics.
"""

import json
import argparse
from pathlib import Path

def normalize_practice_json(data):
    """Normalize math practice JSON."""
    normalized_count = 0

    for question_id, question in data.items():
        changed = False

        # Add display_mode
        if 'display_mode' not in question:
            question['display_mode'] = 'image'
            changed = True

        # Ensure primary_topic and primary_subtopic exist
        if 'primary_topic' not in question:
            question['primary_topic'] = 'unknown'
            changed = True
        if 'primary_subtopic' not in question:
            question['primary_subtopic'] = 'unknown'
            changed = True

        # Note: practice questions have year="practice" and session="mixed"
        # which is fine - these are not from specific exam sessions

        if changed:
            normalized_count += 1

    return normalized_count

def normalize_physics_json(data):
    """Normalize physics JSON."""
    normalized_count = 0

    for question_id, question in data.items():
        changed = False

        # Add display_mode
        if 'display_mode' not in question:
            question['display_mode'] = 'image'
            changed = True

        # Ensure primary_topic and primary_subtopic exist
        if 'primary_topic' not in question:
            question['primary_topic'] = 'unknown'
            changed = True
        if 'primary_subtopic' not in question:
            question['primary_subtopic'] = 'unknown'
            changed = True

        # Extract year, session, TZ from question_id if not present
        # Example: Q34_2015_May_TZ1
        if 'year' not in question or not question.get('year'):
            parts = question_id.split('_')
            if len(parts) >= 2:
                question['year'] = parts[1]
                changed = True

        if 'session' not in question or not question.get('session'):
            parts = question_id.split('_')
            if len(parts) >= 3:
                question['session'] = parts[2]
                changed = True

        if 'tz' not in question or not question.get('tz'):
            parts = question_id.split('_')
            tz = None
            for part in parts:
                if part.startswith('TZ'):
                    tz = part
                    break
            question['tz'] = tz
            changed = True

        if changed:
            normalized_count += 1

    return normalized_count

def normalize_economics_json(data):
    """Normalize economics JSON (already done in create_economics_folders.py)."""
    normalized_count = 0

    for question_id, question in data.items():
        changed = False

        # Ensure topic -> primary_topic
        if 'topic' in question and 'primary_topic' not in question:
            question['primary_topic'] = question['topic']
            changed = True

        # Economics doesn't have subtopics, use topic as subtopic
        if 'primary_subtopic' not in question:
            question['primary_subtopic'] = question.get('primary_topic', question.get('topic', 'Unknown'))
            changed = True

        # Add display_mode
        if 'display_mode' not in question:
            question['display_mode'] = 'text'
            changed = True

        # Ensure is_15_marker exists (default False)
        if 'is_15_marker' not in question:
            part_b = question.get('part_b', '')
            question['is_15_marker'] = '[15 marks]' in part_b or '[15]' in part_b
            changed = True

        if changed:
            normalized_count += 1

    return normalized_count

def normalize_json_files(dry_run=True):
    """Normalize all JSON files."""

    base_dir = Path('/home/xiaohe/stuff/claudable/data')

    # Load all JSON files
    practice_path = base_dir / 'practice_classification_results.json'
    physics_path = base_dir / 'physics_classification_results.json'
    economics_path = base_dir / 'economics_classification_results.json'

    with open(practice_path, 'r') as f:
        practice_data = json.load(f)

    with open(physics_path, 'r') as f:
        physics_data = json.load(f)

    with open(economics_path, 'r', encoding='utf-8') as f:
        economics_data = json.load(f)

    print(f"{'='*60}")
    print(f"JSON Normalization ({'DRY RUN' if dry_run else 'LIVE'})")
    print(f"{'='*60}\n")

    # Normalize each JSON
    print("Normalizing practice_classification_results.json...")
    practice_count = normalize_practice_json(practice_data)
    print(f"  Normalized {practice_count}/{len(practice_data)} entries\n")

    print("Normalizing physics_classification_results.json...")
    physics_count = normalize_physics_json(physics_data)
    print(f"  Normalized {physics_count}/{len(physics_data)} entries\n")

    print("Normalizing economics_classification_results.json...")
    economics_count = normalize_economics_json(economics_data)
    print(f"  Normalized {economics_count}/{len(economics_data)} entries\n")

    # Show sample normalized entry from each
    print("Sample normalized entries:")
    print("\nMath (practice):")
    sample_math = list(practice_data.values())[0]
    print(f"  display_mode: {sample_math.get('display_mode')}")
    print(f"  primary_topic: {sample_math.get('primary_topic')}")
    print(f"  primary_subtopic: {sample_math.get('primary_subtopic')}")

    print("\nPhysics:")
    sample_physics = list(physics_data.values())[0]
    print(f"  display_mode: {sample_physics.get('display_mode')}")
    print(f"  primary_topic: {sample_physics.get('primary_topic')}")
    print(f"  primary_subtopic: {sample_physics.get('primary_subtopic')}")
    print(f"  year: {sample_physics.get('year')}")
    print(f"  session: {sample_physics.get('session')}")
    print(f"  tz: {sample_physics.get('tz')}")

    print("\nEconomics:")
    sample_econ = list(economics_data.values())[0]
    print(f"  display_mode: {sample_econ.get('display_mode')}")
    print(f"  primary_topic: {sample_econ.get('primary_topic')}")
    print(f"  primary_subtopic: {sample_econ.get('primary_subtopic')}")
    print(f"  is_15_marker: {sample_econ.get('is_15_marker')}")

    if dry_run:
        print("\nDRY RUN: No changes made. Run with --execute to apply changes.")
        return True

    # Write updated JSON files
    print("\nWriting updated JSON files...")

    with open(practice_path, 'w') as f:
        json.dump(practice_data, f, indent=2)
    print(f"  ✓ {practice_path.name}")

    with open(physics_path, 'w') as f:
        json.dump(physics_data, f, indent=2)
    print(f"  ✓ {physics_path.name}")

    with open(economics_path, 'w', encoding='utf-8') as f:
        json.dump(economics_data, f, indent=2, ensure_ascii=False)
    print(f"  ✓ {economics_path.name}")

    print("\nNormalization complete!")
    return True

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Normalize JSON field names')
    parser.add_argument('--execute', action='store_true',
                       help='Execute normalization (default is dry-run)')
    args = parser.parse_args()

    success = normalize_json_files(dry_run=not args.execute)
    exit(0 if success else 1)
