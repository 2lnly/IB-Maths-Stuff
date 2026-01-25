"""Main classifier orchestrator."""

import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .api_client import OllamaClient
from .claude_client import ClaudeClient
from .config import Config, get_topic_for_subtopic
from .progress import ProgressTracker
from .prompts import CLASSIFICATION_PROMPT


@dataclass
class Question:
    """Represents a single exam question."""
    question_id: str
    path: Path
    year: str
    paper: str
    session: str
    question_num: str
    image_paths: List[Path]


class Classifier:
    """Main classifier that orchestrates the classification process."""

    def __init__(self, config: Config, num_workers: int = 5):
        self.config = config
        self.progress = ProgressTracker(config.progress_file)
        self.client: Optional[OllamaClient] = None
        self.num_workers = num_workers
        self._lock = threading.Lock()
        self._completed = 0
        self._failed = 0
        self._processed = 0

    def discover_questions(self) -> List[Question]:
        """Discover all questions in the questions directory."""
        questions = []
        questions_dir = self.config.questions_dir

        if not questions_dir.exists():
            print(f"Error: Questions directory not found: {questions_dir}")
            return []

        # Check if this is practice/ structure (paper 1/paper 2/paper 3) or output/ structure
        has_paper_folders = any(
            d.is_dir() and d.name.lower().startswith("paper")
            for d in questions_dir.iterdir()
        )

        if has_paper_folders:
            # Pattern: practice/paper N/QNN/
            for paper_dir in sorted(questions_dir.iterdir()):
                if not paper_dir.is_dir() or not paper_dir.name.lower().startswith("paper"):
                    continue

                paper_name = paper_dir.name.replace(" ", "").title()  # "paper 1" -> "Paper1"

                for q_dir in sorted(paper_dir.iterdir()):
                    if not q_dir.is_dir() or not q_dir.name.startswith("Q"):
                        continue

                    # Find question images (not answer images)
                    q_images = sorted(q_dir.glob("question_p*.png"))
                    if not q_images:
                        continue

                    # Build question ID
                    q_id = f"{paper_name}_{q_dir.name}"

                    questions.append(Question(
                        question_id=q_id,
                        path=q_dir,
                        year="practice",
                        paper=paper_name,
                        session="mixed",
                        question_num=q_dir.name,
                        image_paths=q_images,
                    ))
        else:
            # Pattern: output/YYYY/PaperN/Session/QN/
            for year_dir in sorted(questions_dir.iterdir()):
                if not year_dir.is_dir() or not year_dir.name.isdigit():
                    continue

                for paper_dir in sorted(year_dir.iterdir()):
                    if not paper_dir.is_dir():
                        continue

                    for session_dir in sorted(paper_dir.iterdir()):
                        if not session_dir.is_dir():
                            continue

                        for q_dir in sorted(session_dir.iterdir()):
                            if not q_dir.is_dir() or not q_dir.name.startswith("Q"):
                                continue

                            # Find question images (not answer images)
                            q_images = sorted(q_dir.glob("question_p*.png"))
                            if not q_images:
                                continue

                            # Build question ID
                            q_id = f"{year_dir.name}_{paper_dir.name}_{session_dir.name}_{q_dir.name}"

                            questions.append(Question(
                                question_id=q_id,
                                path=q_dir,
                                year=year_dir.name,
                                paper=paper_dir.name,
                                session=session_dir.name,
                                question_num=q_dir.name,
                                image_paths=q_images,
                            ))

        return questions

    def classify_question(self, question: Question) -> Optional[Dict[str, Any]]:
        """Classify a single question using the LLM."""
        if self.client is None:
            raise RuntimeError("Client not initialized. Use run() or initialize client first.")

        result = self.client.classify_question(
            image_paths=question.image_paths,
            prompt=CLASSIFICATION_PROMPT,
            max_retries=self.config.max_retries,
            retry_delay=self.config.retry_delay,
        )

        if result is None:
            return None

        # Validate and enrich result
        return self._validate_result(result, question)

    def _validate_result(self, result: Dict[str, Any], question: Question) -> Dict[str, Any]:
        """Validate and enrich classification result."""
        # Handle both old and new format
        topic = result.get("topic") or result.get("primary_topic", "unknown")
        subtopic = result.get("subtopic") or result.get("primary_subtopic", "unknown")
        desc = result.get("desc") or result.get("description", "")

        # Handle case where model outputs "topic/subtopic" format
        if "/" in topic and subtopic == "unknown":
            parts = topic.split("/")
            topic = parts[0]
            subtopic = parts[1] if len(parts) > 1 else "unknown"

        # Clean up truncated/garbled subtopics
        subtopic = subtopic.split("/")[0]  # Take first part if multiple
        subtopic = subtopic.rstrip("_.")   # Remove trailing underscores/dots

        validated = {
            "question_id": question.question_id,
            "path": str(question.path),
            "year": question.year,
            "paper": question.paper,
            "session": question.session,
            "question_num": question.question_num,
            "primary_topic": topic,
            "primary_subtopic": subtopic,
            "description": desc,
        }

        # Validate/normalize subtopic
        validated["primary_subtopic"] = self._normalize_subtopic(validated["primary_subtopic"])

        return validated

    def _normalize_subtopic(self, subtopic: str) -> str:
        """Try to normalize a subtopic name to match taxonomy."""
        # Convert to snake_case and clean
        normalized = subtopic.lower().replace(" ", "_").replace("-", "_")
        normalized = normalized.rstrip("_.")

        # Common mappings for LLM errors
        mappings = {
            "derivatives": "differentiation_basics",
            "derivative": "differentiation_basics",
            "differentiation": "differentiation_basics",
            "integrals": "integration_basics",
            "integral": "integration_basics",
            "integration": "integration_basics",
            "vectors": "vectors_2d_3d",
            "trig": "trigonometric_functions",
            "trigonometry": "trigonometric_functions",
            "probability": "probability_basics",
            "sequences": "sequences_series",
            "series": "sequences_series",
            "complex": "complex_numbers",
            "induction": "proof_induction",
            "proof": "proof_induction",
            "proof_indon": "proof_induction",
            "proof_indi": "proof_induction",
            "proof_indition": "proof_induction",
            "exponential": "exponential_log_functions",
            "logarithm": "exponents_logarithms",
            "logarithms": "exponents_logarithms",
            "exponents": "exponents_logarithms",
            "binomial": "binomial_theorem",
            "polynomial": "polynomials",
            "quadratic": "quadratic_functions",
            "rational": "rational_functions",
            "statistics": "descriptive_statistics",
            "regression": "regression_correlation",
            "hypothesis": "hypothesis_testing",
            "differential": "differential_equations",
            "limits": "limits_continuity",
            "maclaurin": "maclaurin_series",
        }

        # Check for partial matches
        for key, value in mappings.items():
            if key in normalized:
                return value

        return normalized

    def _process_question(self, question: Question, total: int) -> Tuple[str, bool, Optional[Dict]]:
        """Process a single question (called by worker threads)."""
        # Create a client for this thread based on provider
        if self.config.provider == "claude":
            client = ClaudeClient(
                api_key=self.config.anthropic_api_key,
                model=self.config.model,
                timeout=self.config.request_timeout,
            )
        else:
            client = OllamaClient(
                base_url=self.config.ollama_base_url,
                model=self.config.model,
                timeout=self.config.request_timeout,
            )

        try:
            result = client.classify_question(
                image_paths=question.image_paths,
                prompt=CLASSIFICATION_PROMPT,
                max_retries=self.config.max_retries,
                retry_delay=self.config.retry_delay,
            )

            if result is None:
                return question.question_id, False, None

            validated = self._validate_result(result, question)

            # Add delay after processing to reduce GPU load
            if self.config.question_delay > 0:
                time.sleep(self.config.question_delay)

            return question.question_id, True, validated
        finally:
            client.close()

    def run(
        self,
        dry_run: bool = False,
        limit: Optional[int] = None,
        retry_failed: bool = False,
    ) -> Tuple[int, int]:
        """
        Run the classification process.

        Args:
            dry_run: If True, only discover questions without classifying
            limit: Maximum number of questions to process
            retry_failed: If True, retry previously failed questions

        Returns:
            Tuple of (completed_count, failed_count)
        """
        # Discover questions
        print("Discovering questions...")
        questions = self.discover_questions()
        print(f"Found {len(questions)} questions")

        if not questions:
            return 0, 0

        # Filter to pending questions
        if retry_failed:
            pending = [q for q in questions if self.progress.needs_processing(q.question_id)
                       or self.progress.is_failed(q.question_id)]
        else:
            pending = [q for q in questions if self.progress.needs_processing(q.question_id)]

        print(f"Pending: {len(pending)} questions")

        if dry_run:
            print("\nDry run - would process these questions:")
            for q in pending[:20]:
                print(f"  {q.question_id}: {len(q.image_paths)} images")
            if len(pending) > 20:
                print(f"  ... and {len(pending) - 20} more")
            return 0, 0

        if limit:
            pending = pending[:limit]
            print(f"Limited to {limit} questions")

        # Check if LLM is available (skip for Claude)
        if self.config.provider == "ollama":
            test_client = OllamaClient(
                base_url=self.config.ollama_base_url,
                model=self.config.model,
                timeout=self.config.request_timeout,
            )

            if not test_client.is_available():
                print(f"\nError: Ollama not available or model '{self.config.model}' not found.")
                print("Available models:", test_client.list_models())
                print("\nMake sure Ollama is running and pull a vision model:")
                print("  ollama pull llama3.2-vision")
                print("  # or")
                print("  ollama pull llava")
                test_client.close()
                return 0, 0
            test_client.close()
        elif self.config.provider == "claude":
            if not self.config.anthropic_api_key:
                print("\nError: Anthropic API key required for Claude provider.")
                print("Use --api-key to provide your API key.")
                return 0, 0

        self._completed = 0
        self._failed = 0
        self._processed = 0
        total = len(pending)
        start_time = time.time()

        print(f"\nProcessing with {self.num_workers} parallel workers...")

        try:
            with ThreadPoolExecutor(max_workers=self.num_workers) as executor:
                # Submit all tasks
                future_to_question = {
                    executor.submit(self._process_question, q, total): q
                    for q in pending
                }

                # Process completed tasks
                for future in as_completed(future_to_question):
                    question = future_to_question[future]
                    try:
                        q_id, success, result = future.result()

                        with self._lock:
                            self._processed += 1
                            if success and result:
                                self.progress.mark_completed(q_id, result)
                                self._completed += 1
                                topic = result.get("primary_topic", "?")
                                subtopic = result.get("primary_subtopic", "?")
                                print(f"[{self._processed}/{total}] {q_id} -> {topic}/{subtopic}")
                            else:
                                self.progress.mark_failed(q_id, "Classification failed")
                                self._failed += 1
                                print(f"[{self._processed}/{total}] {q_id} -> FAILED")

                            # Save progress periodically
                            if self._processed % self.config.save_interval == 0:
                                self.progress.save()
                                elapsed = time.time() - start_time
                                rate = self._processed / elapsed * 60
                                print(f"  [Saved progress. Rate: {rate:.1f} questions/min]")

                    except Exception as e:
                        with self._lock:
                            self._processed += 1
                            self._failed += 1
                            self.progress.mark_failed(question.question_id, str(e))
                            print(f"[{self._processed}/{total}] {question.question_id} -> ERROR: {e}")

        except KeyboardInterrupt:
            print("\n\nInterrupted by user. Saving progress...")
        finally:
            self.progress.save()

        # Export final results
        self.progress.export_results(self.config.results_file)

        elapsed = time.time() - start_time
        rate = self._completed / elapsed * 60 if elapsed > 0 else 0
        print(f"\n{'='*50}")
        print(f"Classification complete!")
        print(f"  Completed: {self._completed}")
        print(f"  Failed: {self._failed}")
        print(f"  Time: {elapsed:.1f}s ({rate:.1f} questions/min)")

        return self._completed, self._failed
