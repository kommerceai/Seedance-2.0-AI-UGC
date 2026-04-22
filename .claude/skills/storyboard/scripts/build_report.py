#!/usr/bin/env python3
"""
build_report.py — write an HTML report for a storyboard run.

Shows final video, each shot MP4, each shot's prompt, and the storyboard JSON.

Usage:
  python3 build_report.py --storyboard path/to/storyboard.json [--out report.html]
"""

import argparse
import html
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import load_storyboard_safe


HTML_TMPL = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>Storyboard — {run_id}</title>
<style>
  body {{ font-family: -apple-system, system-ui, sans-serif; max-width: 920px; margin: 2rem auto; padding: 0 1rem; color: #1a1a1a; }}
  h1 {{ margin-bottom: 0.25rem; }}
  .meta {{ color: #666; font-size: 0.9rem; margin-bottom: 2rem; }}
  .shot {{ border: 1px solid #e0e0e0; border-radius: 8px; padding: 1rem; margin-bottom: 1rem; }}
  .shot h3 {{ margin: 0 0 0.5rem; }}
  .prompt {{ background: #fafafa; padding: 0.75rem; border-radius: 6px; white-space: pre-wrap; font-family: ui-monospace, monospace; font-size: 0.85rem; }}
  video {{ width: 100%; max-width: 480px; border-radius: 6px; display: block; margin-top: 0.5rem; }}
  .final video {{ max-width: 100%; }}
  details {{ margin-top: 2rem; }}
  pre {{ background: #0d1117; color: #c9d1d9; padding: 1rem; border-radius: 6px; overflow-x: auto; font-size: 0.8rem; }}
</style>
</head>
<body>
<h1>{run_id}</h1>
<div class="meta">
  Mode: <b>{mode}</b> — {total_duration}s, {aspect_ratio}, {format_style} style
  — created {created_at}
</div>

{final_html}

<h2>Shots</h2>
{shots_html}

<details>
<summary>storyboard.json</summary>
<pre>{raw_json}</pre>
</details>
</body>
</html>
"""


def shot_block(shot, shots_dir, report_dir):
    mp4 = shots_dir / f"{shot['idx']:02d}.mp4"
    if mp4.exists():
        rel = os.path.relpath(mp4, report_dir)
        video_tag = f'<video controls src="{rel}"></video>'
    else:
        video_tag = '<em>no local MP4 yet</em>'
    return (
        f'<div class="shot">'
        f'<h3>Shot {shot["idx"]} — {shot["role"]} — {shot["duration"]}s</h3>'
        f'<div class="prompt">{html.escape(shot["prompt"])}</div>'
        f'{video_tag}'
        f'</div>'
    )


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--storyboard", required=True)
    p.add_argument("--out")
    args = p.parse_args()

    sb_path = Path(args.storyboard)
    sb = load_storyboard_safe(sb_path)

    out_path = Path(args.out) if args.out else sb_path.parent / "report.html"
    report_dir = out_path.parent

    shots_dir = sb_path.parent / "shots"
    shots_html = "\n".join(shot_block(s, shots_dir, report_dir) for s in sb["shots"])

    final_video = sb.get("final_video")
    if not final_video:
        candidate = sb_path.parent / "final.mp4"
        if candidate.exists():
            final_video = str(candidate)

    final_html = ""
    if final_video and Path(final_video).exists():
        rel = os.path.relpath(final_video, report_dir)
        final_html = f'<div class="final"><h2>Final</h2><video controls src="{rel}"></video></div>'

    out_path.write_text(HTML_TMPL.format(
        run_id=sb["run_id"],
        mode=sb["mode"],
        total_duration=sb["total_duration"],
        aspect_ratio=sb["aspect_ratio"],
        format_style=sb.get("format_style", ""),
        created_at=sb.get("created_at", ""),
        final_html=final_html,
        shots_html=shots_html,
        raw_json=html.escape(json.dumps(sb, indent=2)),
    ))
    print(str(out_path))


if __name__ == "__main__":
    main()
