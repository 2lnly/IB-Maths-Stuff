#!/usr/bin/env python3
"""CLI for IB Math AA HL Question Classifier."""

import argparse
import sys
from pathlib import Path

from classifier.config import Config
from classifier.classifier import Classifier
from classifier.symlink_builder import SymlinkBuilder


def cmd_classify(args):
    """Run the classification process."""
    config = Config(
        questions_dir=Path(args.questions_dir),
        results_file=Path(args.output),
        provider=args.provider,
        model=args.model,
        ollama_base_url=args.ollama_url,
        anthropic_api_key=args.api_key,
    )

    classifier = Classifier(config, num_workers=args.workers)
    completed, failed = classifier.run(
        dry_run=args.dry_run,
        limit=args.limit,
        retry_failed=args.retry_failed,
    )

    if not args.dry_run:
        print(f"\nResults saved to: {config.results_file}")


def cmd_build(args):
    """Build the topic folder structure."""
    config = Config(
        results_file=Path(args.input),
        topics_dir=Path(args.topics_dir),
    )

    builder = SymlinkBuilder(config)
    builder.build(
        include_secondary=args.include_secondary,
        dry_run=args.dry_run,
    )


def cmd_status(args):
    """Show classification status and statistics."""
    config = Config(
        results_file=Path(args.input),
        progress_file=Path(args.progress_file),
    )

    # Show progress
    from classifier.progress import ProgressTracker
    progress = ProgressTracker(config.progress_file)
    stats = progress.get_stats()
    print(f"Progress: {stats['completed']} completed, {stats['failed']} failed")

    # Show topic breakdown if results exist
    if config.results_file.exists():
        builder = SymlinkBuilder(config)
        builder.print_stats()


def cmd_models(args):
    """List available Ollama models."""
    from classifier.api_client import OllamaClient

    client = OllamaClient(base_url=args.ollama_url)
    models = client.list_models()

    if models:
        print("Available Ollama models:")
        for m in models:
            # Mark vision-capable models
            is_vision = any(v in m.lower() for v in ["llava", "vision", "bakllava"])
            marker = " (vision)" if is_vision else ""
            print(f"  {m}{marker}")
    else:
        print("No models found. Is Ollama running?")
        print(f"Tried connecting to: {args.ollama_url}")


def main():
    parser = argparse.ArgumentParser(
        description="Classify IB Math AA HL exam questions using local LLM",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Check available models
  python classify.py models

  # Dry run to see what would be processed
  python classify.py classify --dry-run

  # Classify first 10 questions
  python classify.py classify --limit 10

  # Resume classification (automatically skips completed)
  python classify.py classify

  # Check status
  python classify.py status

  # Build topic folder structure
  python classify.py build
        """
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # classify command
    p_classify = subparsers.add_parser("classify", help="Classify questions")
    p_classify.add_argument(
        "--questions-dir", "-q",
        default="output",
        help="Directory containing questions (default: output)"
    )
    p_classify.add_argument(
        "--output", "-o",
        default="classification_results.json",
        help="Output file for results (default: classification_results.json)"
    )
    p_classify.add_argument(
        "--provider", "-p",
        default="ollama",
        choices=["ollama", "claude"],
        help="LLM provider to use (default: ollama)"
    )
    p_classify.add_argument(
        "--model", "-m",
        default="llama3.2-vision",
        help="Model to use (default: llama3.2-vision for ollama, claude-3-5-haiku-20241022 for claude)"
    )
    p_classify.add_argument(
        "--api-key",
        default="",
        help="Anthropic API key (required for --provider claude)"
    )
    p_classify.add_argument(
        "--ollama-url",
        default="http://localhost:11434",
        help="Ollama API URL (default: http://localhost:11434)"
    )
    p_classify.add_argument(
        "--limit", "-l",
        type=int,
        help="Limit number of questions to process"
    )
    p_classify.add_argument(
        "--dry-run", "-n",
        action="store_true",
        help="Only show what would be done"
    )
    p_classify.add_argument(
        "--retry-failed",
        action="store_true",
        help="Retry previously failed questions"
    )
    p_classify.add_argument(
        "--workers", "-w",
        type=int,
        default=5,
        help="Number of parallel workers (default: 5)"
    )
    p_classify.set_defaults(func=cmd_classify)

    # build command
    p_build = subparsers.add_parser("build", help="Build topic folder structure")
    p_build.add_argument(
        "--input", "-i",
        default="classification_results.json",
        help="Input results file (default: classification_results.json)"
    )
    p_build.add_argument(
        "--topics-dir", "-t",
        default="topics",
        help="Output topics directory (default: topics)"
    )
    p_build.add_argument(
        "--include-secondary",
        action="store_true",
        help="Also create symlinks for secondary topics"
    )
    p_build.add_argument(
        "--dry-run", "-n",
        action="store_true",
        help="Only show what would be done"
    )
    p_build.set_defaults(func=cmd_build)

    # status command
    p_status = subparsers.add_parser("status", help="Show classification status")
    p_status.add_argument(
        "--input", "-i",
        default="classification_results.json",
        help="Input results file (default: classification_results.json)"
    )
    p_status.add_argument(
        "--progress-file",
        default="classification_progress.json",
        help="Progress file (default: classification_progress.json)"
    )
    p_status.set_defaults(func=cmd_status)

    # models command
    p_models = subparsers.add_parser("models", help="List available Ollama models")
    p_models.add_argument(
        "--ollama-url",
        default="http://localhost:11434",
        help="Ollama API URL (default: http://localhost:11434)"
    )
    p_models.set_defaults(func=cmd_models)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()
