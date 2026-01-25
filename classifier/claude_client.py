"""Claude API client for classification."""

import base64
import io
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from anthropic import Anthropic
from PIL import Image


class ClaudeClient:
    """Client for Claude API with vision support."""

    def __init__(
        self,
        api_key: str,
        model: str = "claude-3-5-haiku-20241022",
        timeout: float = 60.0,
    ):
        self.model = model
        self.timeout = timeout
        self.client = Anthropic(api_key=api_key, timeout=timeout)

    def close(self):
        """Close the client."""
        pass  # Anthropic client doesn't need explicit closing

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

    def _encode_image(self, image_path: Path) -> bytes:
        """Read image file as bytes."""
        with open(image_path, "rb") as f:
            return f.read()

    def _prepare_image(self, image_paths: List[Path]) -> bytes:
        """Prepare image(s) for sending to Claude."""
        if len(image_paths) == 1:
            return self._encode_image(image_paths[0])
        else:
            return self._concatenate_images(image_paths)

    def classify_question(
        self,
        image_paths: List[Path],
        prompt: str,
        max_retries: int = 3,
        retry_delay: float = 1.0,
    ) -> Optional[Dict[str, Any]]:
        """
        Send images to Claude for classification.

        Args:
            image_paths: List of image paths (for multi-page questions)
            prompt: The classification prompt
            max_retries: Number of retries on failure
            retry_delay: Delay between retries in seconds

        Returns:
            Parsed JSON response or None on failure
        """
        image_data = self._prepare_image(image_paths)
        image_b64 = base64.standard_b64encode(image_data).decode("utf-8")

        last_error = None
        for attempt in range(max_retries):
            try:
                message = self.client.messages.create(
                    model=self.model,
                    max_tokens=512,
                    messages=[
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "image",
                                    "source": {
                                        "type": "base64",
                                        "media_type": "image/png",
                                        "data": image_b64,
                                    },
                                },
                                {
                                    "type": "text",
                                    "text": prompt,
                                },
                            ],
                        }
                    ],
                )

                response_text = message.content[0].text

                # Parse JSON from response
                import json
                try:
                    return json.loads(response_text.strip())
                except json.JSONDecodeError:
                    # Try to extract JSON from response
                    import re
                    match = re.search(r'\{[^}]+\}', response_text)
                    if match:
                        return json.loads(match.group(0))
                    last_error = f"Failed to parse JSON from: {response_text[:200]}"
                    time.sleep(retry_delay * (attempt + 1))

            except Exception as e:
                last_error = str(e)
                if "rate_limit" in str(e).lower():
                    time.sleep(retry_delay * (attempt + 1) * 2)
                else:
                    time.sleep(retry_delay * (attempt + 1))

        print(f"  Error after {max_retries} attempts: {last_error}")
        return None
