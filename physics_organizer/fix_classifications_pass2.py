"""Second pass: Fix general category misclassifications."""

import json
from pathlib import Path

def fix_general_category():
    """Fix items in 'general' that should be in proper topics."""

    results_file = Path("physics_classification_results.json")

    with open(results_file, 'r') as f:
        results = json.load(f)

    fixed = 0

    for q_id, data in results.items():
        topic = data['primary_topic']
        subtopic = data['primary_subtopic']

        # Fix general category based on subtopic
        if topic == 'general':
            if subtopic in ['work_energy_power', 'forces', 'kinematics', 'mechanics', 'circular_motion', 'momentum_impulse', 'gravitation']:
                data['primary_topic'] = 'mechanics'
                fixed += 1
            elif subtopic in ['circuits', 'electric_fields', 'magnetic_fields', 'electromagnetic_induction', 'electric_current']:
                data['primary_topic'] = 'electricity_magnetism'
                fixed += 1
            elif subtopic in ['wave_properties', 'wave_phenomena', 'standing_waves', 'simple_harmonic_motion', 'doppler_effect']:
                data['primary_topic'] = 'waves'
                fixed += 1
            elif subtopic in ['temperature_heat', 'kinetic_theory', 'thermodynamics', 'heat_transfer']:
                data['primary_topic'] = 'thermal_physics'
                fixed += 1

        # Fix thermal_physics items with wrong subtopics
        if topic == 'thermal_physics' and subtopic in ['work_energy_power', 'forces', 'kinematics']:
            data['primary_topic'] = 'mechanics'
            fixed += 1

        # Fix electricity_magnetism with wrong subtopics
        if topic == 'electricity_magnetism' and subtopic in ['circular_motion', 'work_energy_power', 'forces']:
            data['primary_topic'] = 'mechanics'
            fixed += 1

    # Save results
    with open(results_file, 'w') as f:
        json.dump(results, f, indent=2)

    print(f"✅ Fixed {fixed} more classifications")

    # Show stats
    stats = {}
    for q_id, data in results.items():
        key = f"{data['primary_topic']}/{data['primary_subtopic']}"
        stats[key] = stats.get(key, 0) + 1

    print(f"\nTop 20 topic/subtopic combinations after second pass:")
    for key, count in sorted(stats.items(), key=lambda x: -x[1])[:20]:
        print(f"  {key}: {count}")

    # Show summary by main topic
    main_topics = {}
    for q_id, data in results.items():
        topic = data['primary_topic']
        main_topics[topic] = main_topics.get(topic, 0) + 1

    print(f"\n📊 Summary by main topic:")
    for topic, count in sorted(main_topics.items(), key=lambda x: -x[1]):
        print(f"  {topic}: {count}")

if __name__ == "__main__":
    fix_general_category()
