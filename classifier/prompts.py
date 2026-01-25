"""Prompt templates for classification."""

from .config import TOPIC_TAXONOMY

def build_classification_prompt() -> str:
    """Build the classification prompt with topic taxonomy."""

    # Build compact topic list
    all_subtopics = []
    for topic_key, topic_data in TOPIC_TAXONOMY.items():
        for st in topic_data["subtopics"]:
            all_subtopics.append(f"{topic_key}/{st}")

    subtopics_text = ", ".join(all_subtopics)

    return f"""Classify this IB Math HL exam question.

VALID CATEGORIES (use EXACTLY one of these):
{subtopics_text}

Respond with ONLY this JSON (no extra text):
{{"topic":"<topic>","subtopic":"<subtopic>","desc":"<10 word description>"}}

Example: {{"topic":"calculus","subtopic":"differentiation_basics","desc":"Find derivative of polynomial function"}}"""


CLASSIFICATION_PROMPT = build_classification_prompt()
