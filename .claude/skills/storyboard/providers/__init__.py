"""Video provider abstraction — pick the backend per run."""

import os
from typing import Optional

from .base import VideoProvider, SubmitResult, StatusResult


def get_provider(name: Optional[str] = None) -> VideoProvider:
    """Resolve a provider by name. Order: explicit arg → STORYBOARD_PROVIDER env → 'enhancor'."""
    name = (name or os.environ.get("STORYBOARD_PROVIDER") or "enhancor").lower()
    if name == "enhancor":
        from .enhancor import EnhancorProvider
        return EnhancorProvider()
    if name == "fal":
        from .fal import FalProvider
        return FalProvider()
    raise ValueError(f"unknown provider: {name!r} (supported: enhancor, fal)")


__all__ = ["VideoProvider", "SubmitResult", "StatusResult", "get_provider"]
