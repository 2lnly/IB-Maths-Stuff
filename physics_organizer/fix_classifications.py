"""Fix messy physics classifications and reorganize."""

import json
from pathlib import Path
from config import Config

# Proper topic mapping - fix the messy classifications
TOPIC_FIXES = {
    # Merge electricity topics
    'electromagnetism': 'electricity_magnetism',
    'circuit': 'electricity_magnetism',

    # These should be subtopics of mechanics, not top-level topics
    'kinematics': 'mechanics',
    'forces': 'mechanics',
    'work_energy_power': 'mechanics',

    # Generic topics - keep as general for now
    'physics': 'general',
    'other': 'general',
}

# Subtopic fixes - standardize names
SUBTOPIC_FIXES = {
    'circuit': 'circuits',
    'circuit_analysis': 'circuits',
    'electromagnetic_induction': 'electromagnetic_induction',
    'magnetic_fields': 'magnetic_fields',
    'electric_fields': 'electric_fields',
    'electric_current': 'electric_current',

    # When the topic WAS kinematics/forces/work_energy_power but is now mechanics
    'kinematics': 'kinematics',
    'forces': 'forces',
    'work_energy_power': 'work_energy_power',
}

def fix_classifications():
    """Fix the classification results."""

    results_file = Path("physics_classification_results.json")

    with open(results_file, 'r') as f:
        results = json.load(f)

    fixed = 0
    stats = {}

    for q_id, data in results.items():
        original_topic = data['primary_topic']
        original_subtopic = data['primary_subtopic']

        # Fix topic
        if original_topic in TOPIC_FIXES:
            new_topic = TOPIC_FIXES[original_topic]

            # If we're moving kinematics/forces/work_energy_power to mechanics,
            # the old topic name becomes the subtopic
            if original_topic in ['kinematics', 'forces', 'work_energy_power']:
                data['primary_subtopic'] = original_topic

            data['primary_topic'] = new_topic
            fixed += 1

        # Fix subtopic name
        if data['primary_subtopic'] in SUBTOPIC_FIXES:
            data['primary_subtopic'] = SUBTOPIC_FIXES[data['primary_subtopic']]

        # Track stats
        key = f"{data['primary_topic']}/{data['primary_subtopic']}"
        stats[key] = stats.get(key, 0) + 1

    # Save fixed results
    backup_file = Path("physics_classification_results_backup.json")
    import shutil
    shutil.copy(results_file, backup_file)
    print(f"Backed up original to: {backup_file}")

    with open(results_file, 'w') as f:
        json.dump(results, f, indent=2)

    print(f"\n✅ Fixed {fixed} classifications")
    print(f"\nTop 20 topic/subtopic combinations:")
    for key, count in sorted(stats.items(), key=lambda x: -x[1])[:20]:
        print(f"  {key}: {count}")

    return results

if __name__ == "__main__":
    fix_classifications()
