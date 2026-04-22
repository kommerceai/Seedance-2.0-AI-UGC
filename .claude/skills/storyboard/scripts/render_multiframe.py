#!/usr/bin/env python3
"""
render_multiframe.py — submit a storyboard.json as ONE multi_frame Enhancor call.

Single API request, total duration 4-15s, perfect continuity.

Usage:
  python3 render_multiframe.py --storyboard path/to/storyboard.json \
                               --webhook https://webhook.site/<uuid> \
                               [--dry-run] [--no-submit]
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import (
    ENHANCOR_API_KEY, load_json, save_json,
    upload_image, upload_media, enhancor_queue,
    poll_until_complete, download, OUTPUTS_DIR, ensure_webhook,
)


def build_payload(storyboard, webhook_url):
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
        u = upload_image(p)
        if u:
            images.append(u)
    for p in (assets.get("influencers") or [])[:1]:
        u = upload_image(p)
        if u:
            images.append(u)
    for p in (assets.get("moods") or [])[:5]:
        u = upload_image(p)
        if u:
            images.append(u)
    images = images[:9]

    payload = {
        "type": "image-to-video",
        "mode": "multi_frame",
        "aspect_ratio": storyboard.get("aspect_ratio", "9:16"),
        "resolution": storyboard.get("resolution", "480p"),
        "full_access": True,
        "webhook_url": webhook_url,
        "multi_frame_prompts": multi_frame_prompts,
    }
    if images:
        payload["images"] = images
    audio_path = assets.get("audio")
    if audio_path:
        au = upload_media(audio_path)
        if au:
            payload["audios"] = [au]
    return payload


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--storyboard", required=True)
    p.add_argument("--webhook")
    p.add_argument("--dry-run", action="store_true", help="Print payload only, do not upload or submit")
    p.add_argument("--no-submit", action="store_true", help="Upload assets and print payload, but don't POST")
    p.add_argument("--poll", action="store_true", help="Poll /status until terminal and download result")
    args = p.parse_args()

    sb_path = Path(args.storyboard)
    storyboard = load_json(sb_path)

    if args.dry_run:
        preview = {
            "type": "image-to-video",
            "mode": "multi_frame",
            "aspect_ratio": storyboard.get("aspect_ratio", "9:16"),
            "resolution": storyboard.get("resolution", "480p"),
            "full_access": True,
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
    payload = build_payload(storyboard, webhook_url)

    print("PAYLOAD:")
    print(json.dumps(payload, indent=2))

    if args.no_submit:
        return

    if not ENHANCOR_API_KEY:
        print("ENHANCOR_API_KEY not set. Get your key at https://app.enhancor.ai/api-dashboard", file=sys.stderr)
        sys.exit(3)

    request_id = enhancor_queue(payload)
    if not request_id:
        sys.exit(4)

    storyboard["multiframe_request_id"] = request_id
    storyboard["webhook_url"] = webhook_url
    save_json(sb_path, storyboard)
    print(f"SUBMITTED requestId={request_id}")

    if args.poll:
        result = poll_until_complete(request_id)
        storyboard["multiframe_result"] = result
        save_json(sb_path, storyboard)
        if result.get("status") == "COMPLETED" and result.get("result"):
            out_mp4 = sb_path.parent / "final.mp4"
            if download(result["result"], out_mp4):
                OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
                copy_dest = OUTPUTS_DIR / f"{storyboard['run_id']}.mp4"
                try:
                    import shutil
                    shutil.copy2(out_mp4, copy_dest)
                except Exception as e:
                    print(f"  [outputs copy] {e}", file=sys.stderr)
                print(f"DOWNLOADED {out_mp4}")
                print(f"OUTPUTS {copy_dest}")
            else:
                print(f"ERROR downloading {result['result']}", file=sys.stderr)
                sys.exit(5)
        else:
            print(f"STATUS {result.get('status')}: {result.get('error') or result}", file=sys.stderr)
            sys.exit(6)


if __name__ == "__main__":
    main()
