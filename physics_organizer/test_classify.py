"""Test classifier with a sample question."""

import httpx
import json
from config import Config, PHYSICS_TOPICS

config = Config()
model = "llama3.2:3b"

# Create simple test
topics_str = "\n".join([f"- {topic}: {', '.join(subtopics)}"
                       for topic, subtopics in PHYSICS_TOPICS.items()])

prompt = f"""Classify this IB Physics HL question into ONE topic and ONE subtopic.

Available topics and subtopics:
{topics_str}

Question text:
A ball is thrown vertically upward with an initial velocity of 20 m/s. Calculate the maximum height reached.

Respond with ONLY valid JSON in this format:
{{"primary_topic": "topic_name", "primary_subtopic": "subtopic_name"}}

Use exact topic/subtopic names from the list above."""

print("Testing classification...")
print(f"Using model: {model}")
print(f"Ollama URL: {config.ollama_url}")
print()

try:
    client = httpx.Client(timeout=30.0)
    response = client.post(
        f"{config.ollama_url}/api/generate",
        json={
            "model": model,
            "prompt": prompt,
            "stream": False,
            "format": "json"
        }
    )

    result = response.json()
    text = result.get("response", "")

    print(f"Raw response: {text}")
    print()

    # Parse JSON
    classification = json.loads(text)
    print(f"Parsed: {classification}")
    print(f"Topic: {classification.get('primary_topic')}")
    print(f"Subtopic: {classification.get('primary_subtopic')}")

except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()
