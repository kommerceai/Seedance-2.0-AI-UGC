"""Layer 3 — Time-coded architecture.

Per-shot timestamp block and dialogue budget. Scales to each shot's duration.

Pure function. No I/O.
"""

from typing import Dict, Any


def max_words(duration: int) -> int:
    """Dialogue budget: (duration - 3) * 2.5 words/sec, floor 0."""
    return max(0, int((duration - 3) * 2.5))


def timeline(duration: int) -> str:
    """Standard per-shot timeline string."""
    if duration < 4:
        return f"Timeline: 00:00-00:{duration:02d} visual action only, no dialogue."
    end = duration
    dialogue_end = max(1, end - 2)
    return (
        f"Timeline: 00:00-00:01 silent opening, "
        f"00:01-00:{dialogue_end:02d} dialogue window, "
        f"00:{dialogue_end:02d}-00:{end:02d} silent closing."
    )


def build(shot: Dict[str, Any], context: Dict[str, Any]) -> str:
    duration = int(shot["duration"])
    words = max_words(duration)
    parts = [timeline(duration)]
    if words > 0:
        parts.append(f"Dialogue budget for this shot: <= {words} words.")
    else:
        parts.append("No dialogue in this shot.")
    return " ".join(parts)
