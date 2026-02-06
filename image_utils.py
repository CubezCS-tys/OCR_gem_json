"""
Utility functions for handling image data URIs.
"""

import re
import logging

logger = logging.getLogger(__name__)


def normalise_data_uri(image_data: str, default_mime: str = "image/jpeg") -> str:
    """
    Returns a valid <img src="..."> value.

    - If already a data URI, keep it (but remove accidental double-prefixing)
    - If it's raw base64, wrap it into data:<mime>;base64,<...>
    - Strips whitespace/newlines

    Args:
        image_data: Image data (raw base64 or data URI)
        default_mime: MIME type to use if image type cannot be detected

    Returns:
        Valid data URI string
    """
    if not image_data:
        return ""

    s = image_data.strip()

    # If it's already a data URI, keep it
    if s.startswith("data:"):
        # Handle the exact bug: renderer prepends another prefix
        # Example: "data:image/png;base64,data:image/jpeg;base64,/9j..."
        if "base64,data:" in s:
            # keep only the last data:...base64,<payload>
            s = s.split("base64,data:", 1)[1]
            s = "data:" + s
        return s

    # Sometimes people accidentally store "image/jpeg;base64,...." without "data:"
    if "base64," in s[:50] and not s.startswith("data:"):
        return "data:" + s

    # Raw base64: detect png vs jpg by magic prefix
    head = s[:20]
    if head.startswith("iVBORw0"):   # PNG
        mime = "image/png"
    elif head.startswith("/9j/"):    # JPEG
        mime = "image/jpeg"
    else:
        mime = default_mime

    # remove any whitespace/newlines inside base64
    s = re.sub(r"\s+", "", s)
    return f"data:{mime};base64,{s}"
