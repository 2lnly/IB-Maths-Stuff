# Incomplete Text Validation - Implementation Guide

## Overview

This implementation identifies Paper 1 physics questions where the extracted text is incomplete (missing diagram information), which caused AI-generated answers to be incorrect.

## Problem Statement

- Users see the **full question image** including diagrams ✓
- AI was given **only extracted text** when generating answers ✗
- Some questions have wrong AI answers because text extraction missed critical diagram information
- Only a **small subset** of questions (~5-15 out of 1,825) are affected

## Solution

1. **Identify candidates**: Find questions referencing diagrams
2. **Validate with AI**: Use Claude Haiku to check if text alone is complete
3. **Flag incomplete**: Add `text_incomplete` flag to classification data
4. **Warn users**: Display warning banner when showing flagged questions

## Files Modified

### Created:
- **`validate_incomplete_text.py`** - Main validation script
- **`test_validator.py`** - Test script to preview sample questions
- **`VALIDATION_README.md`** - This file

### Modified:
- **`requirements.txt`** - Added `anthropic>=0.39.0`
- **`web/templates/physics.html`** - Added CSS and JavaScript for warning display
- **`data/physics_classification_results.json`** - Will be updated by validator

## Usage

### 1. Install Dependencies

```bash
pip install anthropic
```

### 2. Test Sample Questions (Optional)

```bash
python3 test_validator.py
```

This shows 5 sample questions with diagram references before running the full validation.

### 3. Run Full Validation

```bash
export ANTHROPIC_API_KEY='your-anthropic-api-key-here'
python3 validate_incomplete_text.py
```

The script will:
- Create a backup: `data/physics_classification_results_backup_YYYYMMDD_HHMMSS.json`
- Scan all Paper 1 questions for diagram references (~30-50 questions)
- Validate each with Claude Haiku (~$0.01 total cost)
- Flag questions with incomplete text (~5-15 expected)
- Update `data/physics_classification_results.json`

### 4. Verify Results

List flagged questions:

```bash
python3 -c "
import json
data = json.load(open('data/physics_classification_results.json'))
incomplete = [(qid, info.get('incomplete_reason')) for qid, info in data.items() if info.get('text_incomplete')]
print(f'Total flagged: {len(incomplete)}\n')
for qid, reason in incomplete:
    print(f'{qid}:')
    print(f'  Reason: {reason}\n')
"
```

### 5. Test Frontend

```bash
cd web
python3 app.py
```

Visit http://localhost:5000/physics and load a flagged question to verify the warning displays correctly.

## Expected Results

- **~30-50 questions** will have diagram references
- **~5-15 questions** will be flagged as having incomplete text (tiny handful)
- **~99% of questions** will display normally without warnings
- **Cost**: ~$0.01 (essentially free)

## Frontend Warning Display

Flagged questions show a red warning banner:

```
⚠️ Answer May Be Incorrect
This question's text was incomplete when the AI generated the answer.
The answer shown may be wrong. Please solve it yourself or check the original markscheme.
```

## Data Structure

Questions flagged as incomplete have two new fields in `physics_classification_results.json`:

```json
{
  "Q3_2011_November": {
    "paper": "Paper 1",
    "path": "/home/xiaohe/stuff/claudable/Physics Flattened/Paper 1/Q3_2011_November",
    "primary_topic": "Space, Time & Motion",
    "primary_subtopic": "Forces & Momentum",
    "topic_code": "A",
    "subtopic_code": "A.2",
    "text_incomplete": true,
    "incomplete_reason": "The question references a graph showing force vs time that is not provided in the text. Without seeing the graph, the question cannot be answered."
  }
}
```

## Validation Logic

The validator uses Claude Haiku with this prompt:

> You are reviewing a multiple choice physics question. You have ONLY the text below - you cannot see any images, diagrams, or graphs.
>
> Question text: {question_text}
>
> Analyze if this question:
> 1. Makes complete sense from the text alone
> 2. Can be understood and potentially answered without seeing any visual elements
>
> Respond with JSON:
> {
>   "text_incomplete": true/false,
>   "reason": "explanation of what's missing or why it makes sense"
> }

## Rollback

If needed, restore from backup:

```bash
# Find the backup file
ls -lt data/physics_classification_results_backup_*.json | head -1

# Restore (replace TIMESTAMP with actual timestamp)
cp data/physics_classification_results_backup_TIMESTAMP.json data/physics_classification_results.json
```

## Next Steps

After validation:

1. Review flagged questions manually to verify correctness
2. Consider spot-checking a few flagged questions against their images
3. Commit changes to repository
4. Deploy updated web app

## Cost Estimate

- Only validates ~30-50 questions (those with diagram references)
- Input: ~150 tokens/question × 50 = ~7,500 tokens
- Output: ~75 tokens/question × 50 = ~3,750 tokens
- Claude Haiku rates: $0.25/1M input, $1.25/1M output
- **Total: ~$0.01** (essentially free)
