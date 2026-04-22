"""
fal.ai adapter — wraps fal_client against Seedance (default) or any fal video model.

Model slug via FAL_MODEL env, default 'fal-ai/bytedance/seedance/v1/pro/image-to-video'.
For first_n_last_frames, set FAL_MODEL_FIRST_LAST to the keyframe-specific slug
(default 'fal-ai/bytedance/seedance/v1/pro/first-last-frame-to-video').

fal.ai's hosted Seedance does NOT expose Enhancor's custom `multi_frame` mode.
This adapter raises ValueError if you ask for multi_frame — use chained instead.
"""

import os
import sys
from typing import Optional

from .base import VideoProvider, JobSpec, SubmitResult, StatusResult


DEFAULT_MODEL = "fal-ai/bytedance/seedance/v1/pro/image-to-video"
DEFAULT_MODEL_FIRST_LAST = "fal-ai/bytedance/seedance/v1/pro/first-last-frame-to-video"


def _import_fal():
    try:
        import fal_client  # type: ignore
        return fal_client
    except ImportError:
        print(
            "  [fal] fal_client not installed. Run: pip install fal-client",
            file=sys.stderr,
        )
        return None


class FalProvider(VideoProvider):
    name = "fal"
    api_key_env = "FAL_KEY"

    def __init__(self) -> None:
        self.model = os.environ.get("FAL_MODEL", DEFAULT_MODEL)
        self.model_first_last = os.environ.get(
            "FAL_MODEL_FIRST_LAST", DEFAULT_MODEL_FIRST_LAST
        )
        # in-memory map of request_id → (model_slug, submitted_handle)
        # fal's handle is the object returned by submit(); we hold it to poll status
        self._handles: dict = {}

    # ---- file upload ----

    def upload_image(self, path: str) -> Optional[str]:
        if not path:
            return None
        if str(path).startswith("http"):
            return str(path)
        if not os.path.exists(path):
            print(f"  [fal/upload] missing: {path}", file=sys.stderr)
            return None
        fal_client = _import_fal()
        if not fal_client:
            return None
        try:
            return fal_client.upload_file(path)
        except Exception as e:
            print(f"  [fal/upload] error {path}: {e}", file=sys.stderr)
            return None

    # fal serves the same CDN for audio/video; reuse upload_file
    upload_media = upload_image  # type: ignore

    # ---- payload translation ----

    def _pick_model(self, spec: JobSpec) -> str:
        if spec.mode == "first_n_last_frames":
            return self.model_first_last
        return self.model

    def _build_arguments(self, spec: JobSpec) -> dict:
        """Translate canonical JobSpec → fal Seedance arguments."""
        if spec.mode == "multi_frame":
            raise ValueError(
                "fal.ai's Seedance does not expose Enhancor's multi_frame mode. "
                "Use --mode chained (first_n_last_frames) instead."
            )

        args: dict = {
            "aspect_ratio": spec.aspect_ratio,
            "resolution": spec.resolution,
        }

        # Seedance on fal uses `prompt` + `image_url` for image-to-video,
        # and `first_image_url` + `last_image_url` for first-last.
        if spec.prompt:
            args["prompt"] = spec.prompt
        if spec.duration is not None:
            args["duration"] = str(spec.duration)

        if spec.mode == "first_n_last_frames":
            if spec.first_frame_image:
                args["first_image_url"] = spec.first_frame_image
            if spec.last_frame_image:
                args["last_image_url"] = spec.last_frame_image
        else:
            # Generic image-to-video: feed the first available image as the conditioning frame.
            img = None
            if spec.images:
                img = spec.images[0]
            elif spec.products:
                img = spec.products[0]
            elif spec.influencers:
                img = spec.influencers[0]
            if img:
                args["image_url"] = img

        # fal ignores full_access / webhook_url at the model layer — webhooks
        # are handled via submit()'s webhook_url kwarg, set below.

        # Allow per-run overrides to pass through
        extras = dict(spec.extras or {})
        extras.pop("full_access", None)  # Enhancor-only
        args.update(extras)
        return args

    # ---- API calls ----

    def submit(self, spec: JobSpec) -> Optional[SubmitResult]:
        fal_client = _import_fal()
        if not fal_client:
            return None
        if not os.environ.get("FAL_KEY"):
            print("  [fal] FAL_KEY not set", file=sys.stderr)
            return None

        try:
            model = self._pick_model(spec)
            arguments = self._build_arguments(spec)
        except ValueError as e:
            print(f"  [fal] {e}", file=sys.stderr)
            return None

        try:
            submit_kwargs = {"arguments": arguments}
            if spec.webhook_url:
                submit_kwargs["webhook_url"] = spec.webhook_url
            handle = fal_client.submit(model, **submit_kwargs)
            request_id = getattr(handle, "request_id", None) or getattr(handle, "id", None)
            if not request_id:
                print(f"  [fal] submit returned no request_id: {handle!r}", file=sys.stderr)
                return None
            self._handles[request_id] = (model, handle)
            return SubmitResult(request_id=request_id, raw={"model": model})
        except Exception as e:
            print(f"  [fal] submit error: {e}", file=sys.stderr)
            return None

    def status(self, request_id: str) -> Optional[StatusResult]:
        fal_client = _import_fal()
        if not fal_client or not request_id:
            return None

        model, handle = self._handles.get(request_id, (self.model, None))
        try:
            if handle is not None:
                st = handle.status()
            else:
                st = fal_client.status(model, request_id)
        except Exception as e:
            print(f"  [fal/status] {e}", file=sys.stderr)
            return None

        # fal events: Queued / InProgress / Completed (class names)
        label = type(st).__name__ if st is not None else "UNKNOWN"
        status_map = {
            "Queued": "IN_QUEUE",
            "InProgress": "IN_PROGRESS",
            "Completed": "COMPLETED",
            "Failed": "FAILED",
        }
        mapped = status_map.get(label, "PENDING")

        result_url = None
        error = None
        if mapped == "COMPLETED":
            try:
                result = handle.get() if handle is not None else fal_client.result(model, request_id)
                # Seedance result shape: {"video": {"url": "..."}}
                if isinstance(result, dict):
                    video = result.get("video") or result.get("output") or {}
                    if isinstance(video, dict):
                        result_url = video.get("url")
                    elif isinstance(video, str):
                        result_url = video
            except Exception as e:
                error = f"could not fetch result: {e}"
                mapped = "FAILED"

        return StatusResult(
            request_id=request_id,
            status=mapped,
            result_url=result_url,
            error=error,
            raw={"fal_event": label},
        )
