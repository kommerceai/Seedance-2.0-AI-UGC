#!/usr/bin/env python3
"""
concat_shots.py — stitch shots/NN.mp4 into final.mp4 via ffmpeg concat.

Tries fast stream-copy first; falls back to re-encode when codecs disagree.

Usage:
  python3 concat_shots.py --storyboard path/to/storyboard.json [--out final.mp4] [--reencode]
"""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import load_storyboard_safe, save_json, OUTPUTS_DIR


def ffmpeg_concat_copy(list_file, out_path):
    r = subprocess.run(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(list_file),
         "-c", "copy", str(out_path)],
        capture_output=True, text=True, timeout=600,
    )
    return r.returncode == 0


def ffmpeg_concat_reencode(list_file, out_path):
    r = subprocess.run(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(list_file),
         "-c:v", "libx264", "-preset", "fast", "-crf", "20",
         "-c:a", "aac", "-b:a", "128k", str(out_path)],
        capture_output=True, text=True, timeout=900,
    )
    if r.returncode != 0:
        print(r.stderr, file=sys.stderr)
    return r.returncode == 0


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--storyboard", required=True)
    p.add_argument("--out")
    p.add_argument("--reencode", action="store_true", help="Skip stream-copy, go straight to re-encode")
    args = p.parse_args()

    sb_path = Path(args.storyboard)
    storyboard = load_storyboard_safe(sb_path)

    shots_dir = sb_path.parent / "shots"
    shot_files = sorted(shots_dir.glob("[0-9][0-9].mp4"))
    if not shot_files:
        print(f"ERROR: no shot MP4s in {shots_dir}", file=sys.stderr)
        sys.exit(2)

    expected = len(storyboard["shots"])
    if len(shot_files) != expected:
        print(
            f"ERROR: found {len(shot_files)} MP4s but storyboard has {expected} shots. "
            f"Re-run render_chained.py with --start-shot N to fill gaps before concat.",
            file=sys.stderr,
        )
        sys.exit(3)

    list_file = sb_path.parent / "concat_list.txt"
    with open(list_file, "w") as f:
        for sf in shot_files:
            f.write(f"file '{sf.resolve()}'\n")

    out_path = Path(args.out) if args.out else sb_path.parent / "final.mp4"

    success = False
    if not args.reencode:
        print("  [concat] attempting stream-copy…")
        success = ffmpeg_concat_copy(list_file, out_path)
        if success:
            print(f"  [concat] stream-copy OK → {out_path}")

    if not success:
        print("  [concat] re-encoding…")
        success = ffmpeg_concat_reencode(list_file, out_path)
        if success:
            print(f"  [concat] re-encode OK → {out_path}")

    if not success:
        print("ERROR: ffmpeg concat failed both modes", file=sys.stderr)
        sys.exit(3)

    # Copy into assets/outputs so the Control Center shows it
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    copy_dest = OUTPUTS_DIR / f"{storyboard['run_id']}.mp4"
    try:
        shutil.copy2(out_path, copy_dest)
        print(f"  [outputs] copied to {copy_dest}")
    except Exception as e:
        print(f"  [outputs] copy failed: {e}", file=sys.stderr)

    storyboard["final_video"] = str(out_path)
    storyboard["outputs_video"] = str(copy_dest)
    save_json(sb_path, storyboard)
    print(str(out_path))


if __name__ == "__main__":
    main()
