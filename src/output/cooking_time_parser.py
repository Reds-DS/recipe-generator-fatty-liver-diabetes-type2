"""
Extracts total cooking time from instruction text.
Used to ensure the displayed cooking time matches what the reader actually follows.
"""
import re

_DURATION_RE = re.compile(r"(\d+)\s*minutes?")


def extract_total_cooking_time(instructions: list[str], fallback: int = 0) -> int:
    """Sum all durations (in minutes) found across instruction steps.

    Returns the total, or *fallback* if no durations are found.
    """
    total = 0
    for step in instructions:
        for match in _DURATION_RE.finditer(step):
            total += int(match.group(1))
    return total if total > 0 else fallback
