"""
VideoProvider interface — every backend (Enhancor, fal.ai, future Higgsfield, etc.)
implements this. Storyboard scripts only talk to this interface.

Canonical job spec (what we send in): mode + prompt(s) + images + audio + timing.
Each provider translates that to its own wire format.
"""

from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List


# ---- canonical job spec (provider-agnostic) ----

@dataclass
class JobSpec:
    """What the skill sends to a provider. Provider translates to its own API shape."""
    mode: str                              # "multi_frame" | "first_n_last_frames" | "image_to_video"
    aspect_ratio: str = "9:16"
    resolution: str = "480p"               # "480p" | "720p"
    duration: Optional[int] = None         # seconds, for single-prompt modes
    prompt: Optional[str] = None           # top-level prompt (single-prompt modes)
    multi_frame_prompts: Optional[List[Dict[str, Any]]] = None  # [{"prompt": str, "duration": int}]
    images: List[str] = field(default_factory=list)      # URLs (post-upload)
    products: List[str] = field(default_factory=list)    # URLs (ugc mode on Enhancor)
    influencers: List[str] = field(default_factory=list) # URLs (ugc mode on Enhancor)
    first_frame_image: Optional[str] = None              # URL
    last_frame_image: Optional[str] = None               # URL
    audios: List[str] = field(default_factory=list)      # URLs
    webhook_url: Optional[str] = None
    full_access: bool = True               # Enhancor-specific; fal silently ignores
    extras: Dict[str, Any] = field(default_factory=dict) # provider-specific overrides


# ---- provider return types ----

@dataclass
class SubmitResult:
    request_id: str
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class StatusResult:
    request_id: str
    status: str                     # "PENDING" | "IN_PROGRESS" | "COMPLETED" | "FAILED" | "TIMEOUT"
    result_url: Optional[str] = None
    error: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict)


# ---- abstract provider ----

class VideoProvider:
    """Abstract base. Concrete: EnhancorProvider, FalProvider."""

    name: str = "unknown"

    # required env var for auth (used by CLI to give clear error messages)
    api_key_env: str = ""

    def __init__(self) -> None:
        pass

    def ready(self) -> bool:
        """True if this provider has the credentials it needs."""
        import os
        return bool(self.api_key_env and os.environ.get(self.api_key_env))

    # ---- API surface every provider implements ----

    def upload_image(self, path: str) -> Optional[str]:
        """Upload a local image and return a public URL. Pass-through for URLs."""
        raise NotImplementedError

    def upload_media(self, path: str) -> Optional[str]:
        """Upload a local audio/video and return a public URL. Pass-through for URLs."""
        raise NotImplementedError

    def submit(self, spec: JobSpec) -> Optional[SubmitResult]:
        """POST the job. Returns SubmitResult with request_id, or None on failure."""
        raise NotImplementedError

    def status(self, request_id: str) -> Optional[StatusResult]:
        """Fetch status. Returns StatusResult or None on failure."""
        raise NotImplementedError

    def poll_until_complete(
        self, request_id: str, timeout_s: int = 1800, interval_s: int = 20
    ) -> StatusResult:
        """Poll status() until COMPLETED/FAILED or timeout."""
        import time
        import sys
        deadline = time.time() + timeout_s
        last_status = None
        while time.time() < deadline:
            s = self.status(request_id)
            if s:
                if s.status != last_status:
                    print(f"  [{self.name}] {request_id[:8]}… → {s.status}")
                    last_status = s.status
                if s.status in ("COMPLETED", "FAILED"):
                    return s
            time.sleep(interval_s)
        print(f"  [{self.name}] {request_id[:8]}… → TIMEOUT", file=sys.stderr)
        return StatusResult(request_id=request_id, status="TIMEOUT")
