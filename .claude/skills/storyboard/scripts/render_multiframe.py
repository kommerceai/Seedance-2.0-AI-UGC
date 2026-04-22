#!/usr/bin/env python3
"""
render_multiframe.py — submit a storyboard.json as ONE multi_frame call.

Enhancor-only mode: single API request, total duration 4-15s, perfect continuity.
fal.ai's Seedance does NOT expose multi_frame — use render_chained.py for fal.

Usage:
  python3 render_multiframe.py --storyboard path/to/storyboard.json \
                               [--provider enhancor|fal] \
                               [--webhook https://webhook.site/<uuid>] \
                               [--dry-run] [--no-submit] [--poll]
"""

import argparse
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _common import save_json, load_storyboard_safe, download, OUTPUTS_DIR, ensure_webhook
from providers import get_provider
from providers.base import JobSpec


def build_spec(storyboard, webhook_url, provider):
    if storyboard["mode"] != "multi_frame":
        print(f"ERROR: storyboard mode is '{storyboard['mode']}', expected 'multi_frame'", file=sys.stderr)
        sys.exit(2)

    total = sum(s["duration"] for s in storyboard["shots"])
    if not (4 <= total <= 15):
        print(f"ERROR: multi_frame total duration must be 4-15s, got {total}", file=sys.stderr)
        sys.exit(2)

    multi_frame_prompts = [
        {"prompt": s["prompt"], "duration": s["duration"]} for s in storyboard["shots"]
    ]

    assets = storyboard.get("assets", {})
    images = []
    for p in (assets.get("products") or [])[:1]:
        u = provider.upload_image(p)
        if u:
            images.append(u)
    for p in (assets.get("influencers") or [])[:1]:
        u = provider.upload_image(p)
        if u:
            images.append(u)
    for p in (assets.get("moods") or [])[:5]:
        u = provider.upload_image(p)
        if u:
            images.append(u)
    images = images[:9]

    audios = []
    audio_path = assets.get("audio")
    if audio_path:
        au = provider.upload_media(audio_path)
        if au:
            audios.append(au)

    return JobSpec(
        mode="multi_frame",
        aspect_ratio=storyboard.get("aspect_ratio", "9:16"),
        resolution=storyboard.get("resolution", "480p"),
        multi_frame_prompts=multi_frame_prompts,
        images=images,
        audios=audios,
        webhook_url=webhook_url,
        full_access=True,
    )


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--storyboard", required=True)
    p.add_argument("--provider", default=None, help="enhancor (default) | fal")
    p.add_argument("--webhook")
    p.add_argument("--dry-run", action="store_true", help="Print payload only, do not upload or submit")
    p.add_argument("--no-submit", action="store_true", help="Upload assets and print payload, but don't POST")
    p.add_argument("--poll", action="store_true", help="Poll status until terminal and download result")
    args = p.parse_args()

    sb_path = Path(args.storyboard)
    storyboard = load_storyboard_safe(sb_path)

    provider = get_provider(args.provider)
    if provider.name == "fal":
        print(
            "ERROR: fal.ai's Seedance does not expose multi_frame mode. "
            "Re-run build_storyboard with --mode chained and use render_chained.py.",
            file=sys.stderr,
        )
        sys.exit(2)

    if args.dry_run:
        preview = {
            "provider": provider.name,
            "mode": "multi_frame",
            "aspect_ratio": storyboard.get("aspect_ratio", "9:16"),
            "resolution": storyboard.get("resolution", "480p"),
            "webhook_url": "(will be generated before submit)",
            "multi_frame_prompts": [
                {"prompt": s["prompt"], "duration": s["duration"]} for s in storyboard["shots"]
            ],
            "images": "(product + subject + moods, uploaded at submit time)",
            "audios": "(uploaded if audio asset is in storyboard and user approved)" if storyboard.get("assets", {}).get("audio") else None,
        }
        print(json.dumps(preview, indent=2))
        return

    webhook_url = ensure_webhook(args.webhook)
    spec = build_spec(storyboard, webhook_url, provider)

    # Show canonical spec + the provider's actual wire payload
    print(f"PROVIDER: {provider.name}")
    print("SPEC:")
    print(json.dumps(spec.__dict__, indent=2, default=str))

    if args.no_submit:
        return

    if not provider.ready():
        print(f"ERROR: {provider.api_key_env} not set for provider '{provider.name}'.", file=sys.stderr)
        if provider.name == "enhancor":
            print("Get your key at https://app.enhancor.ai/api-dashboard", file=sys.stderr)
        sys.exit(3)

    submit_res = provider.submit(spec)
    if not submit_res:
        sys.exit(4)

    storyboard["provider"] = provider.name
    storyboard["multiframe_request_id"] = submit_res.request_id
    storyboard["webhook_url"] = webhook_url
    save_json(sb_path, storyboard)
    print(f"SUBMITTED [{provider.name}] requestId={submit_res.request_id}")

    if args.poll:
        result = provider.poll_until_complete(submit_res.request_id)
        storyboard["multiframe_result"] = {
            "status": result.status,
            "result_url": result.result_url,
            "error": result.error,
        }
        save_json(sb_path, storyboard)
        if result.status == "COMPLETED" and result.result_url:
            out_mp4 = sb_path.parent / "final.mp4"
            if download(result.result_url, out_mp4):
                OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
                copy_dest = OUTPUTS_DIR / f"{storyboard['run_id']}.mp4"
                try:
                    shutil.copy2(out_mp4, copy_dest)
                except Exception as e:
                    print(f"  [outputs copy] {e}", file=sys.stderr)
                print(f"DOWNLOADED {out_mp4}")
                print(f"OUTPUTS {copy_dest}")
            else:
                print(f"ERROR downloading {result.result_url}", file=sys.stderr)
                sys.exit(5)
        else:
            print(f"STATUS {result.status}: {result.error or result.raw}", file=sys.stderr)
            sys.exit(6)


if __name__ == "__main__":
    main()
