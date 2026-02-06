"""Flatten the physics folder structure."""

import shutil
from pathlib import Path
from config import Config

def flatten_paper(paper_dir: Path, output_dir: Path):
    """Flatten a paper folder by moving all Q* folders to the paper root."""
    print(f"\nFlattening {paper_dir.name}...")

    output_paper = output_dir / paper_dir.name
    output_paper.mkdir(parents=True, exist_ok=True)

    moved_count = 0

    # Find all Q* folders nested in session folders
    for session_dir in paper_dir.iterdir():
        if not session_dir.is_dir():
            continue

        for question_dir in session_dir.iterdir():
            if not question_dir.is_dir() or not question_dir.name.startswith('Q'):
                continue

            # New name: Q27_2017_May_TZ1
            new_name = f"{question_dir.name}_{session_dir.name}"
            dest = output_paper / new_name

            # Copy the question folder
            if not dest.exists():
                shutil.copytree(question_dir, dest)
                moved_count += 1
                if moved_count % 100 == 0:
                    print(f"  Moved {moved_count} questions...")

    print(f"  ✓ Moved {moved_count} questions to {output_paper}")
    return moved_count

def main():
    config = Config()

    print("=" * 60)
    print("Flattening Physics folder structure")
    print("=" * 60)

    # Create output directory
    config.flattened_dir.mkdir(parents=True, exist_ok=True)

    total_moved = 0

    # Flatten each paper
    for paper in ["Paper 1", "Paper 2", "Paper 3"]:
        paper_dir = config.base_dir / paper
        if paper_dir.exists():
            count = flatten_paper(paper_dir, config.flattened_dir)
            total_moved += count

    print(f"\n{'=' * 60}")
    print(f"✅ Flattening complete!")
    print(f"   Total questions moved: {total_moved}")
    print(f"   Output: {config.flattened_dir}")
    print(f"{'=' * 60}")

if __name__ == "__main__":
    main()
