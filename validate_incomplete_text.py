#!/usr/bin/env python3
"""
Find Paper 1 questions where text extraction is incomplete.
These questions have wrong AI-generated answers because the AI couldn't see diagrams.
"""

import json
import os
import sys
from pathlib import Path
from anthropic import Anthropic
from datetime import datetime

# Keywords indicating diagram references
DIAGRAM_KEYWORDS = [
    'diagram', 'figure', 'graph', 'shown', 'above', 'below',
    'table', 'chart', 'which diagram', 'the graph', 'as shown',
    'in the diagram', 'the figure'
]

def has_diagram_reference(text):
    """Check if question text references a diagram."""
    text_lower = text.lower()
    return any(keyword in text_lower for keyword in DIAGRAM_KEYWORDS)

def validate_text_completeness(client, question_text):
    """Use Claude Haiku to check if question text is complete."""

    prompt = f"""You are reviewing a multiple choice physics question. You have ONLY the text below - you cannot see any images, diagrams, or graphs.

Question text:
{question_text}

Analyze if this question:
1. Makes complete sense from the text alone
2. Can be understood and potentially answered without seeing any visual elements

Respond with JSON:
{{
  "text_incomplete": true/false,
  "reason": "explanation of what's missing or why it makes sense"
}}

Mark text_incomplete=true if:
- The question references visual elements you cannot see
- The text is ambiguous or unclear without the visual
- Critical information needed to answer is in a diagram/graph you don't have access to"""

    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=300,
        messages=[{"role": "user", "content": prompt}]
    )

    response_text = message.content[0].text
    # Extract JSON from response (handle markdown code blocks)
    if '```json' in response_text:
        response_text = response_text.split('```json')[1].split('```')[0].strip()
    elif '```' in response_text:
        response_text = response_text.split('```')[1].split('```')[0].strip()

    return json.loads(response_text)

def main():
    # Load API key
    api_key = os.environ.get('ANTHROPIC_API_KEY')
    if not api_key and len(sys.argv) > 1:
        api_key = sys.argv[1]
    if not api_key:
        print("Error: Provide API key via ANTHROPIC_API_KEY env var or as argument")
        sys.exit(1)

    client = Anthropic(api_key=api_key)

    # Load classification data
    data_file = Path('data/physics_classification_results.json')
    with open(data_file, 'r') as f:
        data = json.load(f)

    # Backup original
    backup_file = data_file.parent / f'physics_classification_results_backup_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
    with open(backup_file, 'w') as f:
        json.dump(data, f, indent=2)
    print(f"Backup saved: {backup_file}")

    # Find Paper 1 questions with diagram references
    paper1_with_diagrams = []
    for qid, info in data.items():
        if info.get('paper') != 'Paper 1':
            continue

        text_file = Path(f'Physics Flattened/Paper 1/{qid}/question_text.txt')
        if not text_file.exists():
            continue

        question_text = text_file.read_text()
        if has_diagram_reference(question_text):
            paper1_with_diagrams.append((qid, question_text))

    print(f"Found {len(paper1_with_diagrams)} Paper 1 questions with diagram references")
    print(f"Validating text completeness...\n")

    flagged = 0
    for i, (qid, question_text) in enumerate(paper1_with_diagrams, 1):
        try:
            result = validate_text_completeness(client, question_text)

            if result['text_incomplete']:
                data[qid]['text_incomplete'] = True
                data[qid]['incomplete_reason'] = result['reason']
                flagged += 1
                print(f"[{i}/{len(paper1_with_diagrams)}] ⚠️  {qid}: INCOMPLETE")
                print(f"    Reason: {result['reason']}\n")
            else:
                print(f"[{i}/{len(paper1_with_diagrams)}] ✓ {qid}: Complete")

        except Exception as e:
            print(f"[{i}/{len(paper1_with_diagrams)}] ❌ {qid}: Error - {e}")

    # Save updated data
    with open(data_file, 'w') as f:
        json.dump(data, f, indent=2)

    print(f"\n{'='*60}")
    print(f"Done! {flagged} questions flagged as having incomplete text.")
    print(f"These questions may have incorrect AI-generated answers.")
    print(f"{'='*60}")

if __name__ == '__main__':
    main()
