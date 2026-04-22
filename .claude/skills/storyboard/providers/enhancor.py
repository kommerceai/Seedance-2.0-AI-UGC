"""Enhancor adapter — wraps the existing Enhancor UGC Full Access API."""

import json
import os
import ssl
import subprocess
import sys
import urllib.error
import urllib.request
from typing import Optional

from .base import VideoProvider, JobSpec, SubmitResult, StatusResult

_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode = ssl.CERT_NONE


class EnhancorProvider(VideoProvider):
    name = "enhancor"
    api_key_env = "ENHANCOR_API_KEY"

    def __init__(self) -> None:
        self.base_url = os.environ.get(
            "ENHANCOR_API_URL",
            "https://apireq.enhancor.ai/api/enhancor-ugc-full-access/v1",
        )
        self.api_key = os.environ.get("ENHANCOR_API_KEY", "")

    # ---- file upload ----

    def upload_image(self, path: str) -> Optional[str]:
        """Images → tmpfiles.org (direct download URL)."""
        if not path:
            return None
        if str(path).startswith("http"):
            return str(path)
        if not os.path.exists(path):
            print(f"  [enhancor/upload] missing: {path}", file=sys.stderr)
            return None
        try:
            r = subprocess.run(
                ["curl", "-s", "-F", f"file=@{path}", "https://tmpfiles.org/api/v1/upload"],
                capture_output=True, text=True, timeout=120,
            )
            resp = json.loads(r.stdout)
            if resp.get("status") == "success":
                page = resp["data"]["url"]
                return page.replace("tmpfiles.org/", "tmpfiles.org/dl/", 1)
        except Exception as e:
            print(f"  [enhancor/upload] error {path}: {e}", file=sys.stderr)
        return None

    def upload_media(self, path: str) -> Optional[str]:
        """Audio/video → uguu.se (tmpfiles too slow for media)."""
        if not path:
            return None
        if str(path).startswith("http"):
            return str(path)
        if not os.path.exists(path):
            print(f"  [enhancor/upload] missing: {path}", file=sys.stderr)
            return None
        try:
            r = subprocess.run(
                ["curl", "-s", "-F", f"files[]=@{path}", "https://uguu.se/upload"],
                capture_output=True, text=True, timeout=180,
            )
            data = json.loads(r.stdout)
            files = data.get("files") or []
            if files and files[0].get("url"):
                return files[0]["url"]
        except Exception as e:
            print(f"  [enhancor/upload] error {path}: {e}", file=sys.stderr)
        return None

    # ---- payload translation ----

    def _build_payload(self, spec: JobSpec) -> dict:
        payload: dict = {
            "type": "image-to-video",
            "mode": spec.mode,
            "aspect_ratio": spec.aspect_ratio,
            "resolution": spec.resolution,
            "full_access": spec.full_access,
            "webhook_url": spec.webhook_url or "https://webhook.site/placeholder",
        }
        if spec.mode == "multi_frame" and spec.multi_frame_prompts:
            payload["multi_frame_prompts"] = spec.multi_frame_prompts
        else:
            if spec.prompt:
                payload["prompt"] = spec.prompt
            if spec.duration is not None:
                payload["duration"] = str(spec.duration)

        if spec.mode == "first_n_last_frames":
            if spec.first_frame_image:
                payload["first_frame_image"] = spec.first_frame_image
            if spec.last_frame_image:
                payload["last_frame_image"] = spec.last_frame_image

        if spec.images:
            payload["images"] = spec.images[:9]
        if spec.products:
            payload["products"] = spec.products
        if spec.influencers:
            payload["influencers"] = spec.influencers
        if spec.audios:
            payload["audios"] = spec.audios[:3]

        payload.update(spec.extras or {})
        return payload

    # ---- API calls ----

    def submit(self, spec: JobSpec) -> Optional[SubmitResult]:
        if not self.api_key:
            print("  [enhancor] ENHANCOR_API_KEY not set", file=sys.stderr)
            return None
        payload = self._build_payload(spec)
        req = urllib.request.Request(
            f"{self.base_url}/queue",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "x-api-key": self.api_key},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=60, context=_SSL_CTX) as resp:
                body = json.loads(resp.read().decode("utf-8"))
                if body.get("success") and body.get("requestId"):
                    return SubmitResult(request_id=body["requestId"], raw=body)
                print(f"  [enhancor] queue error: {body}", file=sys.stderr)
        except urllib.error.HTTPError as e:
            print(f"  [enhancor] HTTP {e.code}: {e.read().decode('utf-8', 'replace')}", file=sys.stderr)
        except Exception as e:
            print(f"  [enhancor] {e}", file=sys.stderr)
        return None

    def status(self, request_id: str) -> Optional[StatusResult]:
        if not self.api_key or not request_id:
            return None
        req = urllib.request.Request(
            f"{self.base_url}/status",
            data=json.dumps({"request_id": request_id}).encode("utf-8"),
            headers={"Content-Type": "application/json", "x-api-key": self.api_key},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30, context=_SSL_CTX) as resp:
                body = json.loads(resp.read().decode("utf-8"))
                return StatusResult(
                    request_id=request_id,
                    status=body.get("status", "UNKNOWN"),
                    result_url=body.get("result"),
                    error=body.get("error"),
                    raw=body,
                )
        except Exception as e:
            print(f"  [enhancor/status] {e}", file=sys.stderr)
            return None
