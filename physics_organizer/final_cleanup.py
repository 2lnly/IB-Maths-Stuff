"""Final cleanup and regenerate folder structure."""

import json
from pathlib import Path
import shutil

def final_cleanup():
    """Final cleanup of remaining issues."""

    results_file = Path("physics_classification_results.json")

    with open(results_file, 'r') as f:
        results = json.load(f)

    fixed = 0

    for q_id, data in results.items():
        topic = data['primary_topic']
        subtopic = data['primary_subtopic']

        # Fix mechanics/mechanics -> mechanics/forces (default)
        if topic == 'mechanics' and subtopic == 'mechanics':
            data['primary_subtopic'] = 'forces'
            fixed += 1

        # Fix any remaining generic subtopics in specific topics
        if topic in ['mechanics', 'electricity_magnetism', 'waves'] and subtopic in ['mixed_topics', 'other', 'exam_technique']:
            if topic == 'mechanics':
                data['primary_subtopic'] = 'forces'
            elif topic == 'electricity_magnetism':
                data['primary_subtopic'] = 'circuits'
            elif topic == 'waves':
                data['primary_subtopic'] = 'wave_properties'
            fixed += 1

    # Save results
    with open(results_file, 'w') as f:
        json.dump(results, f, indent=2)

    print(f"✅ Final cleanup: fixed {fixed} classifications")

    # Show final stats
    stats = {}
    for q_id, data in results.items():
        key = f"{data['primary_topic']}/{data['primary_subtopic']}"
        stats[key] = stats.get(key, 0) + 1

    print(f"\n📊 Final organization (top 15):")
    for key, count in sorted(stats.items(), key=lambda x: -x[1])[:15]:
        print(f"  {key}: {count}")

    # Main topics
    main_topics = {}
    for q_id, data in results.items():
        topic = data['primary_topic']
        main_topics[topic] = main_topics.get(topic, 0) + 1

    print(f"\n📚 By main topic:")
    for topic, count in sorted(main_topics.items(), key=lambda x: -x[1]):
        print(f"  {topic}: {count} questions")

if __name__ == "__main__":
    final_cleanup()
