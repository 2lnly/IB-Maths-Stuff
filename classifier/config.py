"""Configuration and topic taxonomy for the classifier."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List

# IB Math AA HL Topic Taxonomy
TOPIC_TAXONOMY: Dict[str, Dict[str, List[str]]] = {
    "number_algebra": {
        "name": "Number & Algebra",
        "subtopics": [
            "sequences_series",
            "exponents_logarithms",
            "binomial_theorem",
            "complex_numbers",
            "proof_induction",
            "polynomials",
            "systems_of_equations",
        ]
    },
    "functions": {
        "name": "Functions",
        "subtopics": [
            "function_properties",
            "transformations",
            "quadratic_functions",
            "rational_functions",
            "exponential_log_functions",
            "modeling",
            "inverse_functions",
            "composite_functions",
        ]
    },
    "geometry_trigonometry": {
        "name": "Geometry & Trigonometry",
        "subtopics": [
            "trigonometric_functions",
            "trigonometric_identities",
            "trigonometric_equations",
            "vectors_2d_3d",
            "lines_planes",
            "circles_arcs",
            "triangle_geometry",
        ]
    },
    "statistics_probability": {
        "name": "Statistics & Probability",
        "subtopics": [
            "descriptive_statistics",
            "probability_basics",
            "discrete_distributions",
            "continuous_distributions",
            "hypothesis_testing",
            "regression_correlation",
            "combinatorics",
        ]
    },
    "calculus": {
        "name": "Calculus",
        "subtopics": [
            "limits_continuity",
            "differentiation_basics",
            "differentiation_techniques",
            "applications_of_derivatives",
            "integration_basics",
            "integration_techniques",
            "applications_of_integrals",
            "differential_equations",
            "maclaurin_series",
        ]
    },
}


def get_all_subtopics() -> List[str]:
    """Get flat list of all subtopics."""
    subtopics = []
    for topic_data in TOPIC_TAXONOMY.values():
        subtopics.extend(topic_data["subtopics"])
    return subtopics


def get_topic_for_subtopic(subtopic: str) -> str | None:
    """Get the parent topic for a subtopic."""
    for topic_key, topic_data in TOPIC_TAXONOMY.items():
        if subtopic in topic_data["subtopics"]:
            return topic_key
    return None


@dataclass
class Config:
    """Configuration for the classifier."""

    # Paths
    questions_dir: Path = field(default_factory=lambda: Path("output"))
    results_file: Path = field(default_factory=lambda: Path("classification_results.json"))
    progress_file: Path = field(default_factory=lambda: Path("classification_progress.json"))
    topics_dir: Path = field(default_factory=lambda: Path("topics"))

    # LLM settings
    provider: str = "ollama"  # "ollama" or "claude"
    ollama_base_url: str = "http://localhost:11434"
    model: str = "llama3.2-vision"  # or "llava", "llava-llama3", "claude-3-5-haiku-20241022"
    anthropic_api_key: str = ""

    # Processing settings
    batch_size: int = 1  # Process one at a time for vision
    save_interval: int = 25  # Save progress every N questions
    max_retries: int = 3
    retry_delay: float = 2.0
    request_timeout: float = 120.0  # Vision models can be slow
    question_delay: float = 0.0  # Delay between questions (seconds) to reduce GPU load

    # Rate limiting (requests per minute) - less critical for local
    rate_limit: int = 30

    def __post_init__(self):
        """Convert string paths to Path objects."""
        if isinstance(self.questions_dir, str):
            self.questions_dir = Path(self.questions_dir)
        if isinstance(self.results_file, str):
            self.results_file = Path(self.results_file)
        if isinstance(self.progress_file, str):
            self.progress_file = Path(self.progress_file)
        if isinstance(self.topics_dir, str):
            self.topics_dir = Path(self.topics_dir)
