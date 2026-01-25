"""Progress tracking for resumable classification."""

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set


@dataclass
class ProgressTracker:
    """Track classification progress for resumability."""

    progress_file: Path
    completed: Set[str] = field(default_factory=set)
    failed: Dict[str, str] = field(default_factory=dict)  # question_id -> error
    results: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    started_at: Optional[str] = None
    last_saved: Optional[str] = None

    def __post_init__(self):
        if isinstance(self.progress_file, str):
            self.progress_file = Path(self.progress_file)
        self.load()

    def load(self) -> None:
        """Load progress from file if it exists."""
        if self.progress_file.exists():
            try:
                with open(self.progress_file, "r") as f:
                    data = json.load(f)
                self.completed = set(data.get("completed", []))
                self.failed = data.get("failed", {})
                self.results = data.get("results", {})
                self.started_at = data.get("started_at")
                self.last_saved = data.get("last_saved")
                print(f"Loaded progress: {len(self.completed)} completed, {len(self.failed)} failed")
            except (json.JSONDecodeError, IOError) as e:
                print(f"Warning: Could not load progress file: {e}")

    def save(self) -> None:
        """Save progress to file."""
        self.last_saved = datetime.now().isoformat()
        if not self.started_at:
            self.started_at = self.last_saved

        data = {
            "completed": list(self.completed),
            "failed": self.failed,
            "results": self.results,
            "started_at": self.started_at,
            "last_saved": self.last_saved,
            "stats": {
                "total_completed": len(self.completed),
                "total_failed": len(self.failed),
            }
        }

        # Write atomically
        temp_file = self.progress_file.with_suffix(".tmp")
        with open(temp_file, "w") as f:
            json.dump(data, f, indent=2)
        temp_file.replace(self.progress_file)

    def mark_completed(self, question_id: str, result: Dict[str, Any]) -> None:
        """Mark a question as successfully classified."""
        self.completed.add(question_id)
        self.results[question_id] = result
        # Remove from failed if it was there
        self.failed.pop(question_id, None)

    def mark_failed(self, question_id: str, error: str) -> None:
        """Mark a question as failed."""
        self.failed[question_id] = error

    def is_completed(self, question_id: str) -> bool:
        """Check if a question has been classified."""
        return question_id in self.completed

    def is_failed(self, question_id: str) -> bool:
        """Check if a question has failed."""
        return question_id in self.failed

    def needs_processing(self, question_id: str) -> bool:
        """Check if a question needs to be processed."""
        return question_id not in self.completed

    def get_pending_count(self, all_questions: List[str]) -> int:
        """Get count of questions still needing processing."""
        return sum(1 for q in all_questions if self.needs_processing(q))

    def get_stats(self) -> Dict[str, int]:
        """Get progress statistics."""
        return {
            "completed": len(self.completed),
            "failed": len(self.failed),
        }

    def export_results(self, output_file: Path) -> None:
        """Export results to a separate JSON file."""
        with open(output_file, "w") as f:
            json.dump(self.results, f, indent=2)
        print(f"Exported {len(self.results)} results to {output_file}")
