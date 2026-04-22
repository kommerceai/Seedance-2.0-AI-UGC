#!/usr/bin/env python3
"""
Offline tests for the providers/ package.

No network, no API calls. Mocks fal_client and stubs Enhancor HTTP.

Run:
  python3 .claude/skills/storyboard/scripts/test_providers.py
"""

import os
import sys
import traceback
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from providers import get_provider
from providers.base import JobSpec, VideoProvider, StatusResult
from providers.enhancor import EnhancorProvider
from providers.fal import FalProvider


_PASS = []
_FAIL = []


def _t(name):
    def deco(fn):
        try:
            fn()
            _PASS.append(name)
            print(f"  [PASS] {name}")
        except AssertionError as e:
            _FAIL.append((name, str(e)))
            print(f"  [FAIL] {name}: {e}")
        except Exception as e:
            _FAIL.append((name, repr(e)))
            print(f"  [ERROR] {name}: {repr(e)}")
            traceback.print_exc()
        return fn
    return deco


# ---- registry ----

@_t("get_provider defaults to enhancor")
def _1():
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("STORYBOARD_PROVIDER", None)
        p = get_provider(None)
        assert p.name == "enhancor", p.name


@_t("get_provider honors explicit arg")
def _2():
    assert get_provider("fal").name == "fal"
    assert get_provider("enhancor").name == "enhancor"


@_t("get_provider honors STORYBOARD_PROVIDER env")
def _3():
    with patch.dict(os.environ, {"STORYBOARD_PROVIDER": "fal"}):
        assert get_provider(None).name == "fal"


@_t("get_provider raises on unknown")
def _4():
    try:
        get_provider("bogus")
    except ValueError:
        return
    raise AssertionError("expected ValueError")


@_t("provider.ready() is False without env var")
def _5():
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("ENHANCOR_API_KEY", None)
        os.environ.pop("FAL_KEY", None)
        assert not EnhancorProvider().ready()
        assert not FalProvider().ready()


@_t("provider.ready() is True with env var")
def _6():
    with patch.dict(os.environ, {"ENHANCOR_API_KEY": "x", "FAL_KEY": "y"}):
        assert EnhancorProvider().ready()
        assert FalProvider().ready()


# ---- Enhancor payload translation ----

@_t("enhancor multi_frame payload shape")
def _7():
    p = EnhancorProvider()
    spec = JobSpec(
        mode="multi_frame",
        aspect_ratio="9:16",
        multi_frame_prompts=[{"prompt": "a", "duration": 3}, {"prompt": "b", "duration": 3}],
        images=["https://x/img.png"],
        audios=["https://x/a.mp3"],
        webhook_url="https://webhook.site/abc",
    )
    payload = p._build_payload(spec)
    assert payload["mode"] == "multi_frame"
    assert payload["multi_frame_prompts"] == spec.multi_frame_prompts
    assert "prompt" not in payload, "multi_frame must not carry top-level prompt"
    assert "duration" not in payload, "multi_frame duration is auto-derived"
    assert payload["full_access"] is True
    assert payload["images"] == spec.images
    assert payload["audios"] == spec.audios


@_t("enhancor first_n_last_frames payload shape")
def _8():
    p = EnhancorProvider()
    spec = JobSpec(
        mode="first_n_last_frames",
        duration=5,
        prompt="shot one",
        first_frame_image="https://x/k1.png",
        audios=["https://x/a.mp3"],
        webhook_url="https://webhook.site/abc",
    )
    payload = p._build_payload(spec)
    assert payload["mode"] == "first_n_last_frames"
    assert payload["prompt"] == "shot one"
    assert payload["duration"] == "5"
    assert payload["first_frame_image"] == "https://x/k1.png"


# ---- fal argument translation ----

@_t("fal rejects multi_frame mode")
def _9():
    p = FalProvider()
    spec = JobSpec(
        mode="multi_frame",
        multi_frame_prompts=[{"prompt": "a", "duration": 3}],
    )
    try:
        p._build_arguments(spec)
    except ValueError as e:
        assert "multi_frame" in str(e).lower()
        return
    raise AssertionError("expected ValueError for multi_frame on fal")


@_t("fal image_to_video uses image_url")
def _10():
    p = FalProvider()
    spec = JobSpec(
        mode="image_to_video",
        duration=5,
        prompt="a scene",
        images=["https://x/img.png"],
    )
    args = p._build_arguments(spec)
    assert args["image_url"] == "https://x/img.png"
    assert args["prompt"] == "a scene"
    assert args["duration"] == "5"
    assert "full_access" not in args, "full_access is Enhancor-only"


@_t("fal first_n_last_frames maps to first_image_url/last_image_url")
def _11():
    p = FalProvider()
    spec = JobSpec(
        mode="first_n_last_frames",
        duration=5,
        prompt="transition",
        first_frame_image="https://x/k1.png",
        last_frame_image="https://x/k2.png",
    )
    args = p._build_arguments(spec)
    assert args["first_image_url"] == "https://x/k1.png"
    assert args["last_image_url"] == "https://x/k2.png"
    assert args["prompt"] == "transition"


@_t("fal extras pass-through (and strip full_access)")
def _12():
    p = FalProvider()
    spec = JobSpec(
        mode="image_to_video",
        duration=5,
        prompt="x",
        images=["https://x/img.png"],
        extras={"seed": 42, "full_access": True},  # full_access must be stripped
    )
    args = p._build_arguments(spec)
    assert args["seed"] == 42
    assert "full_access" not in args


@_t("fal picks first-last model slug for that mode")
def _13():
    p = FalProvider()
    assert "image-to-video" in p._pick_model(JobSpec(mode="image_to_video"))
    assert "first-last" in p._pick_model(JobSpec(mode="first_n_last_frames"))


# ---- fal submit/status with mocked fal_client ----

class _FakeHandle:
    def __init__(self, request_id="fal-req-123"):
        self.request_id = request_id
        self._status_class = "Queued"
        self._result = {"video": {"url": "https://fal.example/v.mp4"}}

    def status(self):
        return type(self._status_class, (), {})()

    def get(self):
        return self._result


@_t("fal submit returns request_id + stashes handle")
def _14():
    fake_fc = SimpleNamespace(
        submit=lambda model, arguments, **kw: _FakeHandle("fal-req-xyz"),
        upload_file=lambda path: "https://fal.cdn/x",
    )
    with patch.dict(sys.modules, {"fal_client": fake_fc}), \
         patch.dict(os.environ, {"FAL_KEY": "test"}):
        p = FalProvider()
        spec = JobSpec(mode="image_to_video", duration=5, prompt="x",
                       images=["https://x/img.png"])
        res = p.submit(spec)
        assert res is not None
        assert res.request_id == "fal-req-xyz"
        assert res.request_id in p._handles


@_t("fal status returns COMPLETED with result_url")
def _15():
    handle = _FakeHandle("fal-req-done")
    handle._status_class = "Completed"
    fake_fc = SimpleNamespace()
    with patch.dict(sys.modules, {"fal_client": fake_fc}):
        p = FalProvider()
        p._handles["fal-req-done"] = (p.model, handle)
        st = p.status("fal-req-done")
        assert st is not None
        assert st.status == "COMPLETED"
        assert st.result_url == "https://fal.example/v.mp4"


@_t("fal status maps Queued/InProgress correctly")
def _16():
    handle = _FakeHandle("fal-req-q")
    handle._status_class = "Queued"
    fake_fc = SimpleNamespace()
    with patch.dict(sys.modules, {"fal_client": fake_fc}):
        p = FalProvider()
        p._handles["fal-req-q"] = (p.model, handle)
        assert p.status("fal-req-q").status == "IN_QUEUE"
        handle._status_class = "InProgress"
        assert p.status("fal-req-q").status == "IN_PROGRESS"


# ---- upload URL pass-through ----

@_t("providers pass through URLs without re-upload")
def _17():
    p = EnhancorProvider()
    assert p.upload_image("https://x/img.png") == "https://x/img.png"
    assert p.upload_media("https://x/a.mp3") == "https://x/a.mp3"


@_t("fal passes URLs through without touching fal_client")
def _18():
    with patch.dict(sys.modules, {"fal_client": SimpleNamespace()}):
        p = FalProvider()
        assert p.upload_image("https://cdn.fal.ai/x.png") == "https://cdn.fal.ai/x.png"


def main():
    total = len(_PASS) + len(_FAIL)
    print(f"\n{len(_PASS)}/{total} passed.")
    if _FAIL:
        print("\nFailures:")
        for name, err in _FAIL:
            print(f"  - {name}: {err}")
        sys.exit(1)


if __name__ == "__main__":
    main()
