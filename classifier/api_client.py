"""Local LLM API client using Ollama."""

import base64
import io
import json
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
from PIL import Image


class OllamaClient:
    """Client for Ollama API with vision support."""

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model: str = "llama3.2-vision",
        timeout: float = 120.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self._client = httpx.Client(timeout=timeout)

    def close(self):
        """Close the HTTP client."""
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def is_available(self) -> bool:
        """Check if Ollama is running and the model is available."""
        try:
            response = self._client.get(f"{self.base_url}/api/tags")
            if response.status_code != 200:
                return False
            data = response.json()
            model_names = [m.get("name", "").split(":")[0] for m in data.get("models", [])]
            return self.model.split(":")[0] in model_names
        except Exception:
            return False

    def list_models(self) -> List[str]:
        """List available models."""
        try:
            response = self._client.get(f"{self.base_url}/api/tags")
            if response.status_code == 200:
                data = response.json()
                return [m.get("name", "") for m in data.get("models", [])]
        except Exception:
            pass
        return []

    def _concatenate_images(self, image_paths: List[Path]) -> bytes:
        """Concatenate multiple images vertically into one."""
        images = [Image.open(p) for p in image_paths]

        # Calculate total dimensions
        max_width = max(img.width for img in images)
        total_height = sum(img.height for img in images)

        # Create combined image
        combined = Image.new("RGB", (max_width, total_height), color="white")

        y_offset = 0
        for img in images:
            # Convert to RGB if necessary
            if img.mode != "RGB":
                img = img.convert("RGB")
            combined.paste(img, (0, y_offset))
            y_offset += img.height

        # Save to bytes
        buffer = io.BytesIO()
        combined.save(buffer, format="PNG")
        return buffer.getvalue()

    def _encode_image(self, image_path: Path) -> str:
        """Encode an image file to base64."""
        with open(image_path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")

    def _encode_images(self, image_paths: List[Path]) -> str:
        """Encode images to base64, concatenating if multiple."""
        if len(image_paths) == 1:
            return self._encode_image(image_paths[0])
        else:
            combined_bytes = self._concatenate_images(image_paths)
            return base64.b64encode(combined_bytes).decode("utf-8")

    def classify_question(
        self,
        image_paths: List[Path],
        prompt: str,
        max_retries: int = 3,
        retry_delay: float = 2.0,
    ) -> Optional[Dict[str, Any]]:
        """
        Send images to Ollama for classification.

        Args:
            image_paths: List of image paths (for multi-page questions)
            prompt: The classification prompt
            max_retries: Number of retries on failure
            retry_delay: Delay between retries in seconds

        Returns:
            Parsed JSON response or None on failure
        """
        # Encode images (concatenate if multiple)
        image_b64 = self._encode_images(image_paths)

        payload = {
            "model": self.model,
            "prompt": prompt,
            "images": [image_b64],
            "stream": False,
            "options": {
                "temperature": 0.1,  # Low temperature for consistent classification
                "num_predict": 512,  # Shorter response needed
            }
        }

        last_error = None
        for attempt in range(max_retries):
            try:
                response = self._client.post(
                    f"{self.base_url}/api/generate",
                    json=payload,
                    timeout=self.timeout,
                )

                if response.status_code != 200:
                    last_error = f"HTTP {response.status_code}: {response.text}"
                    time.sleep(retry_delay * (attempt + 1))
                    continue

                data = response.json()
                response_text = data.get("response", "")

                # Parse JSON from response
                parsed = self._parse_json_response(response_text)
                if parsed:
                    return parsed

                last_error = f"Failed to parse JSON from: {response_text[:200]}"
                time.sleep(retry_delay * (attempt + 1))

            except httpx.TimeoutException:
                last_error = "Request timed out"
                time.sleep(retry_delay * (attempt + 1))
            except Exception as e:
                last_error = str(e)
                time.sleep(retry_delay * (attempt + 1))

        print(f"  Error after {max_retries} attempts: {last_error}")
        return None

    def _parse_json_response(self, text: str) -> Optional[Dict[str, Any]]:
        """Extract and parse JSON from LLM response."""
        # Try direct parse first
        try:
            return json.loads(text.strip())
        except json.JSONDecodeError:
            pass

        # Try to find JSON in markdown code blocks
        patterns = [
            r"```json\s*(.*?)\s*```",
            r"```\s*(.*?)\s*```",
            r"\{.*\}",
        ]

        for pattern in patterns:
            match = re.search(pattern, text, re.DOTALL)
            if match:
                try:
                    json_str = match.group(1) if "```" in pattern else match.group(0)
                    return json.loads(json_str.strip())
                except (json.JSONDecodeError, IndexError):
                    continue

        return None
