"""Master script to run all physics organization steps."""

import subprocess
import sys
from pathlib import Path

def run_step(name: str, script: str):
    """Run a processing step."""
    print(f"\n{'=' * 60}")
    print(f"STEP: {name}")
    print(f"{'=' * 60}\n")

    result = subprocess.run([sys.executable, script], cwd=Path(__file__).parent)

    if result.returncode != 0:
        print(f"\n❌ Step failed: {name}")
        print("   Fix the issue and run again, or run individual steps.")
        return False

    return True

def main():
    print("=" * 60)
    print("IB PHYSICS HL ORGANIZER")
    print("=" * 60)
    print("\nThis will:")
    print("1. Flatten folder structure")
    print("2. Extract text from questions (using Ollama)")
    print("3. Classify questions by topic (using Ollama)")
    print("4. Organize into topic folders with symlinks")
    print("\nMake sure Ollama is running: ollama serve")
    print("=" * 60)

    input("\nPress Enter to continue or Ctrl+C to cancel...")

    steps = [
        ("Flatten Structure", "flatten.py"),
        ("Extract Text", "extract_text.py"),
        ("Classify Topics", "classify.py"),
        ("Organize by Topic", "organize.py")
    ]

    for name, script in steps:
        if not run_step(name, script):
            sys.exit(1)

    print("\n" + "=" * 60)
    print("✅ ALL STEPS COMPLETE!")
    print("=" * 60)
    print("\nYour physics questions are now organized at:")
    print("  Physics By Topic/Paper1/topic/subtopic/QX_SESSION/")
    print("\nEach question folder contains:")
    print("  - question_p*.png (original images)")
    print("  - question_text.txt (extracted text)")
    print("  - answer.txt or answer.png (answer)")
    print("=" * 60)

if __name__ == "__main__":
    main()
