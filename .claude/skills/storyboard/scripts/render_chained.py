#!/usr/bin/env python3
"""
render_chained.py — submit a storyboard.json as N chained first_n_last_frames jobs.

Shot k's last frame becomes shot k+1's first_frame_image. All MP4s land in
<project>/shots/. Concat happens in concat_shots.py.

Works on both Enhancor and fal.ai.

Usage:
  python3 render_chained.py --storyboard path/to/storyboard.json \
                            [--provider enhancor|fal] \
                            [--webhook https://webhook.site/<uuid>] \
                            [--start-shot N] [--dry-run] [--no-submit]

--start-shot lets you resume partway through after a failure.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _common import (
    save_json, load_storyboard_safe, download, ffmpeg_last_frame, ensure_webhook,
)
from providers import get_provider
from providers.base import JobSpec


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--storyboard", required=True)
    p.add_argument("--provider", default=None, help="enhancor (default) | fal")
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

    provider = get_provider(args.provider)

    assets = storyboard.get("assets", {})
    shots_dir = sb_path.parent / "shots"
    shots_dir.mkdir(parents=True, exist_ok=True)

    if args.dry_run:
        print(f"PROVIDER: {provider.name}")
        print("PLANNED JOBS:")
        for s in storyboard["shots"]:
            print(f"  shot {s['idx']} ({s['role']}, {s['duration']}s): "
                  f"first_frame={'<prior shot last frame>' if s['idx'] > 1 else '<product hero>'}")
        return

    webhook_url = ensure_webhook(args.webhook)
    storyboard["webhook_url"] = webhook_url
    storyboard["provider"] = provider.name

    # Pre-upload product + subject
    product_url = None
    if assets.get("products"):
        product_url = provider.upload_image(assets["products"][0])
    subject_url = None
    if assets.get("influencers"):
        subject_url = provider.upload_image(assets["influencers"][0])

    audio_url = None
    if assets.get("audio"):
        audio_url = provider.upload_media(assets["audio"])

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

        if shot_idx == 1:
            first_frame_url = product_url or subject_url
            if not first_frame_url:
                print("ERROR: shot 1 needs a product or subject image in assets", file=sys.stderr)
                sys.exit(3)
        else:
            if not prior_last_frame_url:
                print(f"ERROR: no prior last-frame URL available for shot {shot_idx}; "
                      f"re-run from --start-shot {shot_idx - 1}", file=sys.stderr)
                sys.exit(4)
            first_frame_url = prior_last_frame_url

        spec = JobSpec(
            mode="first_n_last_frames",
            aspect_ratio=storyboard.get("aspect_ratio", "9:16"),
            resolution=storyboard.get("resolution", "480p"),
            duration=shot["duration"],
            prompt=shot["prompt"],
            first_frame_image=first_frame_url,
            images=list(extra_images),
            audios=[audio_url] if audio_url else [],
            webhook_url=webhook_url,
            full_access=True,
        )

        print(f"\n=== SHOT {shot_idx}/{len(storyboard['shots'])} ({shot['role']}, {shot['duration']}s) [{provider.name}] ===")
        print("SPEC:")
        print(json.dumps(spec.__dict__, indent=2, default=str))

        if args.no_submit:
            continue

        if not provider.ready():
            print(f"ERROR: {provider.api_key_env} not set for provider '{provider.name}'.", file=sys.stderr)
            sys.exit(5)

        submit_res = provider.submit(spec)
        if not submit_res:
            print(f"  [err] shot {shot_idx} submit failed; re-run with --start-shot {shot_idx}", file=sys.stderr)
            shot_records[i] = {"request_id": None, "status": "SUBMIT_FAILED"}
            storyboard["shot_records"] = shot_records
            save_json(sb_path, storyboard)
            sys.exit(6)

        print(f"  [queued] shot {shot_idx} requestId={submit_res.request_id}")
        shot_records[i] = {"request_id": submit_res.request_id, "status": "PENDING"}
        storyboard["shot_records"] = shot_records
        save_json(sb_path, storyboard)

        # Poll synchronously — next shot needs this shot's last frame
        result = provider.poll_until_complete(submit_res.request_id)
        shot_records[i] = {
            "request_id": submit_res.request_id,
            "status": result.status,
            "result": result.result_url,
            "error": result.error,
        }

        if result.status != "COMPLETED" or not result.result_url:
            print(f"  [err] shot {shot_idx} ended with status {result.status}: "
                  f"{result.error or result.raw}", file=sys.stderr)
            storyboard["shot_records"] = shot_records
            save_json(sb_path, storyboard)
            sys.exit(7)

        shot_mp4 = shots_dir / f"{shot_idx:02d}.mp4"
        if not download(result.result_url, shot_mp4):
            print(f"  [err] shot {shot_idx} download failed", file=sys.stderr)
            sys.exit(8)
        print(f"  [downloaded] {shot_mp4}")
        shot_records[i]["local_path"] = str(shot_mp4)

        if shot_idx < len(storyboard["shots"]):
            last_png = shots_dir / f"{shot_idx:02d}_last.png"
            if not ffmpeg_last_frame(shot_mp4, last_png):
                print(f"  [err] ffmpeg last-frame extraction failed for shot {shot_idx}", file=sys.stderr)
                sys.exit(9)
            prior_last_frame_url = provider.upload_image(str(last_png))
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
