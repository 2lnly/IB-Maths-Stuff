"""Extract text from question images using Claude Haiku."""

import json
import base64
from pathlib import Path
from typing import Dict, Any, List
import anthropic
from concurrent.futures import ThreadPoolExecutor
import time

# Paths
PRACTICE_DIR = Path(__file__).parent / "practice"
RESULTS_FILE = Path(__file__).parent / "practice_classification_results.json"
PROGRESS_FILE = Path(__file__).parent / "text_extraction_progress.json"
KEY_FILE = Path(__file__).parent / "key"

# Load classification results
with open(RESULTS_FILE, 'r') as f:
    QUESTIONS = json.load(f)

# Load API key
with open(KEY_FILE, 'r') as f:
    api_key = f.read().strip()

# Initialize Claude client
client = anthropic.Anthropic(api_key=api_key)

def load_progress() -> Dict[str, Any]:
    """Load progress from file."""
    if PROGRESS_FILE.exists():
        with open(PROGRESS_FILE, 'r') as f:
            return json.load(f)
    return {"completed": [], "failed": []}

def save_progress(progress: Dict[str, Any]):
    """Save progress to file."""
    with open(PROGRESS_FILE, 'w') as f:
        json.dump(progress, f, indent=2)

def get_question_images(question_path: Path) -> List[Path]:
    """Get all question image paths."""
    images = []
    page_num = 1
    while True:
        img_path = question_path / f"question_p{page_num}.png"
        if img_path.exists():
            images.append(img_path)
            page_num += 1
        else:
            break
    return images

def extract_text_from_images(image_paths: List[Path]) -> str:
    """Extract text from images using Claude Haiku."""
    # Build content with all images
    content = []
    for img_path in image_paths:
        with open(img_path, 'rb') as f:
            image_data = base64.b64encode(f.read()).decode()
        content.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/png",
                "data": image_data
            }
        })

    # Add text prompt
    content.append({
        "type": "text",
        "text": "Extract all text from this image exactly as it appears, including all mathematical notation, equations, and symbols. Preserve the structure and formatting."
    })

    # Call Claude API
    response = client.messages.create(
        model="claude-3-haiku-20240307",
        max_tokens=2000,
        messages=[{
            "role": "user",
            "content": content
        }]
    )

    return response.content[0].text

def process_question(question_id: str, data: Dict[str, Any], progress: Dict[str, Any], total: int) -> bool:
    """Process a single question."""
    if question_id in progress["completed"]:
        return True

    try:
        question_path = Path(data["path"])
        if not question_path.exists():
            print(f"[{len(progress['completed'])+1}/{total}] ❌ {question_id}: Path not found")
            progress["failed"].append(question_id)
            return False

        # Get all question images
        images = get_question_images(question_path)
        if not images:
            print(f"[{len(progress['completed'])+1}/{total}] ❌ {question_id}: No images found")
            progress["failed"].append(question_id)
            return False

        # Extract text
        print(f"[{len(progress['completed'])+1}/{total}] 🔍 {question_id}: Extracting from {len(images)} image(s)...")
        text = extract_text_from_images(images)

        # Save to file
        output_file = question_path / "question_text.txt"
        with open(output_file, 'w') as f:
            f.write(text)

        print(f"[{len(progress['completed'])+1}/{total}] ✅ {question_id}: Saved to {output_file.name}")
        progress["completed"].append(question_id)

        # Save progress every 25 questions
        if len(progress["completed"]) % 25 == 0:
            save_progress(progress)

        return True

    except Exception as e:
        print(f"[{len(progress['completed'])+1}/{total}] ❌ {question_id}: {e}")
        progress["failed"].append(question_id)
        return False

def main():
    """Main extraction loop."""
    print(f"Loading {len(QUESTIONS)} questions from classification results...", flush=True)

    # Load progress
    progress = load_progress()

    # Filter pending questions
    pending = [
        (q_id, data) for q_id, data in QUESTIONS.items()
        if q_id not in progress["completed"] and q_id not in progress["failed"]
    ]

    print(f"Progress: {len(progress['completed'])} completed, {len(progress['failed'])} failed", flush=True)
    print(f"Remaining: {len(pending)} questions\n", flush=True)

    if not pending:
        print("All questions already processed!", flush=True)
        return

    # Process with 15 workers (100k tokens/min limit, ~1500 tokens per image)
    total = len(QUESTIONS)
    with ThreadPoolExecutor(max_workers=15) as executor:
        futures = [
            executor.submit(process_question, q_id, data, progress, total)
            for q_id, data in pending
        ]

        for future in futures:
            future.result()
            time.sleep(0.05)  # Small delay to avoid bursting

    # Save final progress
    save_progress(progress)

    print(f"\n✅ Extraction complete!", flush=True)
    print(f"   Completed: {len(progress['completed'])}", flush=True)
    print(f"   Failed: {len(progress['failed'])}", flush=True)

    if progress["failed"]:
        print(f"\nFailed questions: {', '.join(progress['failed'][:10])}...", flush=True)

if __name__ == "__main__":
    main()
