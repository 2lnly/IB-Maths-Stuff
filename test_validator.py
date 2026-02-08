#!/usr/bin/env python3
"""
Test script to verify the validator logic works on a sample question.
"""

import json
from pathlib import Path

# Load classification data
data_file = Path('data/physics_classification_results.json')
with open(data_file, 'r') as f:
    data = json.load(f)

# Find a few Paper 1 questions with diagram references
DIAGRAM_KEYWORDS = [
    'diagram', 'figure', 'graph', 'shown', 'above', 'below',
    'table', 'chart', 'which diagram', 'the graph', 'as shown',
    'in the diagram', 'the figure'
]

def has_diagram_reference(text):
    """Check if question text references a diagram."""
    text_lower = text.lower()
    return any(keyword in text_lower for keyword in DIAGRAM_KEYWORDS)

paper1_with_diagrams = []
for qid, info in data.items():
    if info.get('paper') != 'Paper 1':
        continue

    text_file = Path(f'Physics Flattened/Paper 1/{qid}/question_text.txt')
    if not text_file.exists():
        continue

    question_text = text_file.read_text()
    if has_diagram_reference(question_text):
        paper1_with_diagrams.append((qid, question_text[:200]))
        if len(paper1_with_diagrams) >= 5:
            break

print(f"Found {len(paper1_with_diagrams)} sample questions with diagram references:\n")
for qid, text_preview in paper1_with_diagrams:
    print(f"{qid}:")
    print(f"  {text_preview}...\n")

print(f"\nTo run the full validation, you'll need to:")
print(f"1. Install anthropic: pip install anthropic")
print(f"2. Set your API key: export ANTHROPIC_API_KEY='your-key-here'")
print(f"3. Run: python3 validate_incomplete_text.py")
