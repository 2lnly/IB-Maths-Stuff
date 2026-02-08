#!/usr/bin/env python3
"""
Relabel Paper 1 economics questions with correct Micro/Macro topics using Claude Haiku.
"""

import json
import os
import sys
from pathlib import Path
from anthropic import Anthropic
from datetime import datetime

def classify_topic(client, question_text):
    """Use Claude Haiku to determine if question is Microeconomics or Macroeconomics."""

    prompt = f"""You are analyzing an IB Economics Paper 1 question. Paper 1 has two sections:
- Section A: Microeconomics (study of individual markets, supply/demand, market structures, market failure)
- Section B: Macroeconomics (study of whole economy, GDP, inflation, unemployment, fiscal/monetary policy)

Question text:
{question_text}

Based on the content, is this question about Microeconomics or Macroeconomics?

Respond with JSON:
{{
  "topic": "Microeconomics" or "Macroeconomics",
  "reason": "brief explanation of why"
}}

Key indicators:
- Microeconomics: individual consumers/firms, supply/demand curves, elasticity, market structures, externalities, merit/demerit goods
- Macroeconomics: aggregate demand/supply, GDP, economic growth, inflation, unemployment, fiscal policy, monetary policy, exchange rates"""

    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=200,
        messages=[{"role": "user", "content": prompt}]
    )

    response_text = message.content[0].text
    # Extract JSON from response
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
    data_file = Path('data/economics_classification_results.json')
    with open(data_file, 'r') as f:
        data = json.load(f)

    # Backup original
    backup_file = data_file.parent / f'economics_classification_results_backup_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
    with open(backup_file, 'w') as f:
        json.dump(data, f, indent=2)
    print(f"Backup saved: {backup_file}")

    # Find Paper 1 questions
    paper1_questions = [(qid, info) for qid, info in data.items() if info.get('paper') == 'Paper 1']

    print(f"Found {len(paper1_questions)} Paper 1 questions")
    print(f"Validating topic labels...\n")

    corrected = 0
    for i, (qid, info) in enumerate(paper1_questions, 1):
        current_topic = info.get('topic', 'Unknown')
        question_text = info.get('full_text', '')

        if not question_text:
            print(f"[{i}/{len(paper1_questions)}] ⚠️  {qid}: No question text found")
            continue

        try:
            result = classify_topic(client, question_text)
            new_topic = result['topic']

            if new_topic != current_topic:
                data[qid]['topic'] = new_topic
                data[qid]['topic_correction_reason'] = result['reason']
                corrected += 1
                print(f"[{i}/{len(paper1_questions)}] 🔄 {qid}: {current_topic} → {new_topic}")
                print(f"    Reason: {result['reason']}\n")
            else:
                print(f"[{i}/{len(paper1_questions)}] ✓ {qid}: {current_topic} (correct)")

        except Exception as e:
            print(f"[{i}/{len(paper1_questions)}] ❌ {qid}: Error - {e}")

    # Save updated data
    with open(data_file, 'w') as f:
        json.dump(data, f, indent=2)

    print(f"\n{'='*60}")
    print(f"Done! {corrected} questions relabeled.")
    print(f"Accuracy: {len(paper1_questions) - corrected}/{len(paper1_questions)} were already correct ({(len(paper1_questions) - corrected)/len(paper1_questions)*100:.1f}%)")
    print(f"{'='*60}")

if __name__ == '__main__':
    main()
