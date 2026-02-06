"""Organize physics questions by topic using symlinks."""

import json
from pathlib import Path
from config import Config

def create_symlink_structure(results_file: Path, config: Config):
    """Create symlinked folder structure organized by topic."""
    print("=" * 60)
    print("Organizing Physics questions by topic")
    print("=" * 60)

    # Load classification results
    with open(results_file, 'r') as f:
        results = json.load(f)

    # Create output directory
    config.topics_dir.mkdir(parents=True, exist_ok=True)

    # Organize by paper -> topic -> subtopic
    created_links = 0

    for question_id, data in results.items():
        paper = data["paper"].replace(" ", "")  # "Paper 1" -> "Paper1"
        topic = data["primary_topic"]
        subtopic = data["primary_subtopic"]
        source_path = Path(data["path"])

        if not source_path.exists():
            print(f"⚠️  Source not found: {source_path}")
            continue

        # Create directory structure: Paper1/topic/subtopic/
        link_dir = config.topics_dir / paper / topic / subtopic
        link_dir.mkdir(parents=True, exist_ok=True)

        # Create symlink
        link_path = link_dir / question_id

        if not link_path.exists():
            # Use relative symlink
            link_path.symlink_to(source_path.resolve())
            created_links += 1

            if created_links % 100 == 0:
                print(f"  Created {created_links} symlinks...")

    print(f"\n{'=' * 60}")
    print(f"✅ Organization complete!")
    print(f"   Total symlinks created: {created_links}")
    print(f"   Output directory: {config.topics_dir}")
    print(f"{'=' * 60}")

    # Print summary
    print("\nSummary by paper:")
    for paper in ["Paper1", "Paper2", "Paper3"]:
        paper_dir = config.topics_dir / paper
        if paper_dir.exists():
            count = sum(1 for _ in paper_dir.glob("*/*/*"))
            print(f"  {paper}: {count} questions")

def main():
    config = Config()
    results_file = Path("physics_classification_results.json")

    if not results_file.exists():
        print(f"❌ Classification results not found: {results_file}")
        print("   Run classify.py first!")
        return

    create_symlink_structure(results_file, config)

if __name__ == "__main__":
    main()
