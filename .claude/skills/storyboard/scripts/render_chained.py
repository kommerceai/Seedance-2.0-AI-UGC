#!/usr/bin/env python3
"""
render_chained.py — submit a storyboard.json as N chained first_n_last_frames jobs.

Shot k's last frame becomes shot k+1's first_frame_image. All MP4s land in
<project>/shots/. Concat happens in concat_shots.py.

Usage:
  python3 render_chained.py --storyboard path/to/storyboard.json \
                            --webhook https://webhook.site/<uuid> \
                            [--start-shot N] [--dry-run] [--no-submit]

--start-shot lets you resume partway through after a failure.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import (
    ENHANCOR_API_KEY, save_json, load_storyboard_safe,
    upload_image, upload_media, enhancor_queue,
    poll_until_complete, download, ffmpeg_last_frame,
    ensure_webhook,
)


def shot_payload(storyboard, shot, first_frame_url, audio_url, webhook_url, extra_images):
    payload = {
        "type": "image-to-video",
        "mode": "first_n_last_frames",
        "aspect_ratio": storyboard.get("aspect_ratio", "9:16"),
        "resolution": storyboard.get("resolution", "480p"),
        "duration": str(shot["duration"]),
        "full_access": True,
        "webhook_url": webhook_url,
        "prompt": shot["prompt"],
        "first_frame_image": first_frame_url,
    }
    if extra_images:
        payload["images"] = extra_images[:9]
    if audio_url:
        payload["audios"] = [audio_url]
    return payload


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--storyboard", required=True)
    p.add_argument("--webhook")
    p.add_argument("--start-shot", type=int, default=1, help="1-indexed shot to resume from")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--no-submit", action="store_true")
    args = p.parse_args()

    sb_path = Path(args.storyboard)
    storyboard = load_storyboard_safe(sb_path)

    if storyboard["mode"] != "chained":
        print(f"ERROR: storyboard mode is '{storyboard['mode']}', expected 'chained'", file=sys.stderr)
        sys.exit(2)

    assets = storyboard.get("assets", {})
    shots_dir = sb_path.parent / "shots"
    shots_dir.mkdir(parents=True, exist_ok=True)

    if args.dry_run:
        print("PLANNED JOBS:")
        for s in storyboard["shots"]:
            print(f"  shot {s['idx']} ({s['role']}, {s['duration']}s): first_frame={'<prior shot last frame>' if s['idx'] > 1 else '<product hero>'}")
        return

    webhook_url = ensure_webhook(args.webhook)
    storyboard["webhook_url"] = webhook_url

    # Pre-upload product image (used as first frame for shot 1 and carried as extra reference)
    product_url = None
    if assets.get("products"):
        product_url = upload_image(assets["products"][0])
    subject_url = None
    if assets.get("influencers"):
        subject_url = upload_image(assets["influencers"][0])

    audio_url = None
    if assets.get("audio"):
        audio_url = upload_media(assets["audio"])

    extra_images = [u for u in (product_url, subject_url) if u]

    shot_records = storyboard.get("shot_records") or [None] * len(storyboard["shots"])
    if len(shot_records) != len(storyboard["shots"]):
        shot_records = [None] * len(storyboard["shots"])

    prior_last_frame_url = None

    for i, shot in enumerate(storyboard["shots"]):
        shot_idx = i + 1
        if shot_idx < args.start_shot:
            rec = shot_records[i] or {}
            prior_last_frame_url = rec.get("last_frame_url")
            continue

        # Determine first_frame_image for this shot
        if shot_idx == 1:
            first_frame_url = product_url or subject_url
            if not first_frame_url:
                print(f"ERROR: shot 1 needs a product or subject image in assets", file=sys.stderr)
                sys.exit(3)
        else:
            if not prior_last_frame_url:
                print(f"ERROR: no prior last-frame URL available for shot {shot_idx}; re-run from --start-shot {shot_idx - 1}", file=sys.stderr)
                sys.exit(4)
            first_frame_url = prior_last_frame_url

        payload = shot_payload(storyboard, shot, first_frame_url, audio_url, webhook_url, extra_images)
        print(f"\n=== SHOT {shot_idx}/{len(storyboard['shots'])} ({shot['role']}, {shot['duration']}s) ===")
        print("PAYLOAD:")
        print(json.dumps(payload, indent=2))

        if args.no_submit:
            continue

        if not ENHANCOR_API_KEY:
            print("ENHANCOR_API_KEY not set. Get your key at https://app.enhancor.ai/api-dashboard", file=sys.stderr)
            sys.exit(5)

        request_id = enhancor_queue(payload)
        if not request_id:
            print(f"  [err] shot {shot_idx} queue failed; re-run with --start-shot {shot_idx}", file=sys.stderr)
            shot_records[i] = {"request_id": None, "status": "QUEUE_FAILED"}
            storyboard["shot_records"] = shot_records
            save_json(sb_path, storyboard)
            sys.exit(6)

        print(f"  [queued] shot {shot_idx} requestId={request_id}")
        shot_records[i] = {"request_id": request_id, "status": "PENDING"}
        storyboard["shot_records"] = shot_records
        save_json(sb_path, storyboard)

        # Must poll synchronously — next shot needs this shot's last frame.
        result = poll_until_complete(request_id)
        shot_records[i] = {"request_id": request_id, **result}

        if result.get("status") != "COMPLETED" or not result.get("result"):
            print(f"  [err] shot {shot_idx} ended with status {result.get('status')}: {result.get('error') or result}", file=sys.stderr)
            storyboard["shot_records"] = shot_records
            save_json(sb_path, storyboard)
            sys.exit(7)

        shot_mp4 = shots_dir / f"{shot_idx:02d}.mp4"
        if not download(result["result"], shot_mp4):
            print(f"  [err] shot {shot_idx} download failed", file=sys.stderr)
            sys.exit(8)
        print(f"  [downloaded] {shot_mp4}")
        shot_records[i]["local_path"] = str(shot_mp4)

        # Extract last frame → upload → stash URL for next shot
        if shot_idx < len(storyboard["shots"]):
            last_png = shots_dir / f"{shot_idx:02d}_last.png"
            if not ffmpeg_last_frame(shot_mp4, last_png):
                print(f"  [err] ffmpeg last-frame extraction failed for shot {shot_idx}", file=sys.stderr)
                sys.exit(9)
            prior_last_frame_url = upload_image(last_png)
            if not prior_last_frame_url:
                print(f"  [err] last-frame upload failed for shot {shot_idx}", file=sys.stderr)
                sys.exit(10)
            shot_records[i]["last_frame_url"] = prior_last_frame_url
            print(f"  [handoff] {last_png.name} → {prior_last_frame_url}")

        storyboard["shot_records"] = shot_records
        save_json(sb_path, storyboard)

    print(f"\nALL {len(storyboard['shots'])} SHOTS COMPLETE. Next step: concat_shots.py")


if __name__ == "__main__":
    main()
