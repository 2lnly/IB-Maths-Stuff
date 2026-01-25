"""Build topic folder structure with symlinks."""

import json
import os
from pathlib import Path
from typing import Dict, Any, List, Optional

from .config import Config, TOPIC_TAXONOMY


class SymlinkBuilder:
    """Build a topic-organized folder structure using symlinks."""

    def __init__(self, config: Config):
        self.config = config

    def load_results(self) -> Dict[str, Dict[str, Any]]:
        """Load classification results from file."""
        if not self.config.results_file.exists():
            print(f"Error: Results file not found: {self.config.results_file}")
            return {}

        with open(self.config.results_file, "r") as f:
            return json.load(f)

    def build(
        self,
        include_secondary: bool = False,
        dry_run: bool = False,
        by_paper: bool = True,
    ) -> int:
        """
        Build the topic folder structure.

        Args:
            include_secondary: If True, also create symlinks for secondary topics
            dry_run: If True, only print what would be done
            by_paper: If True, organize by paper first (paper_1/topic/subtopic)

        Returns:
            Number of symlinks created
        """
        results = self.load_results()
        if not results:
            return 0

        print(f"Building topic structure from {len(results)} classified questions...")

        symlinks_created = 0

        for question_id, data in results.items():
            # Primary topic symlink
            primary_topic = data.get("primary_topic", "unknown")
            primary_subtopic = data.get("primary_subtopic", "unknown")
            question_path = Path(data.get("path", ""))
            paper = data.get("paper", "unknown")

            if not question_path.exists():
                print(f"  Warning: Question path not found: {question_path}")
                continue

            created = self._create_symlink(
                paper=paper if by_paper else None,
                topic=primary_topic,
                subtopic=primary_subtopic,
                question_id=question_id,
                target_path=question_path,
                dry_run=dry_run,
            )
            if created:
                symlinks_created += 1

            # Secondary topics (optional)
            if include_secondary:
                for secondary in data.get("secondary_topics", []):
                    sec_topic = secondary.get("topic", "")
                    sec_subtopic = secondary.get("subtopic", "")
                    if sec_topic and sec_subtopic:
                        created = self._create_symlink(
                            paper=paper if by_paper else None,
                            topic=sec_topic,
                            subtopic=sec_subtopic,
                            question_id=question_id,
                            target_path=question_path,
                            dry_run=dry_run,
                            is_secondary=True,
                        )
                        if created:
                            symlinks_created += 1

        action = "Would create" if dry_run else "Created"
        print(f"\n{action} {symlinks_created} symlinks")
        return symlinks_created

    def _create_topic_folders(self) -> None:
        """Create all topic and subtopic folders."""
        topics_dir = self.config.topics_dir
        topics_dir.mkdir(exist_ok=True)

        for topic_key, topic_data in TOPIC_TAXONOMY.items():
            topic_dir = topics_dir / topic_key
            topic_dir.mkdir(exist_ok=True)

            for subtopic in topic_data["subtopics"]:
                subtopic_dir = topic_dir / subtopic
                subtopic_dir.mkdir(exist_ok=True)

    def _create_symlink(
        self,
        topic: str,
        subtopic: str,
        question_id: str,
        target_path: Path,
        dry_run: bool,
        paper: Optional[str] = None,
        is_secondary: bool = False,
    ) -> bool:
        """Create a single symlink."""
        # Normalize names
        topic = topic.lower().replace(" ", "_").replace("-", "_")
        subtopic = subtopic.lower().replace(" ", "_").replace("-", "_")

        # Normalize paper name if provided
        if paper:
            paper = paper.lower().replace(" ", "_").replace("-", "_")

        # Build link path (with or without paper)
        if paper:
            # Structure: topics/paper_1/topic/subtopic/question_id
            link_dir = self.config.topics_dir / paper / topic / subtopic
        else:
            # Structure: topics/topic/subtopic/question_id
            link_dir = self.config.topics_dir / topic / subtopic

        suffix = "_secondary" if is_secondary else ""
        link_name = f"{question_id}{suffix}"
        link_path = link_dir / link_name

        # Calculate relative path from link location to target
        try:
            # Make target absolute
            target_abs = target_path.resolve()

            # Calculate expected link directory absolute path
            if link_dir.exists():
                link_dir_abs = link_dir.resolve()
            else:
                if paper:
                    link_dir_abs = self.config.topics_dir.resolve() / paper / topic / subtopic
                else:
                    link_dir_abs = self.config.topics_dir.resolve() / topic / subtopic

            # Calculate relative path
            rel_target = os.path.relpath(target_abs, link_dir_abs)

            if dry_run:
                print(f"  {link_path} -> {rel_target}")
                return True

            # Create parent directories if needed
            link_dir.mkdir(parents=True, exist_ok=True)

            # Remove existing symlink if present
            if link_path.is_symlink():
                link_path.unlink()

            # Create symlink
            link_path.symlink_to(rel_target)
            return True

        except Exception as e:
            print(f"  Error creating symlink for {question_id}: {e}")
            return False

    def get_stats(self) -> Dict[str, Any]:
        """Get statistics about the topic structure."""
        results = self.load_results()
        if not results:
            return {"error": "No results file found"}

        # Count by topic
        topic_counts: Dict[str, Dict[str, int]] = {}
        for data in results.values():
            topic = data.get("primary_topic", "unknown")
            subtopic = data.get("primary_subtopic", "unknown")

            if topic not in topic_counts:
                topic_counts[topic] = {}
            topic_counts[topic][subtopic] = topic_counts[topic].get(subtopic, 0) + 1

        return {
            "total_questions": len(results),
            "topics": topic_counts,
        }

    def print_stats(self) -> None:
        """Print statistics about classified questions."""
        stats = self.get_stats()
        if "error" in stats:
            print(stats["error"])
            return

        print(f"\nClassification Statistics ({stats['total_questions']} questions)")
        print("=" * 50)

        for topic_key in sorted(stats["topics"].keys()):
            subtopics = stats["topics"][topic_key]
            topic_name = TOPIC_TAXONOMY.get(topic_key, {}).get("name", topic_key)
            topic_total = sum(subtopics.values())
            print(f"\n{topic_name} ({topic_total})")

            for subtopic in sorted(subtopics.keys()):
                count = subtopics[subtopic]
                print(f"  {subtopic}: {count}")
