#!/usr/bin/env python3
"""
storyboard_agent.py — Claude Agent SDK driver for the /storyboard skill.

Wraps each script in .claude/skills/storyboard/scripts/ as a Claude tool and
lets a Claude agent drive the full pipeline end-to-end:
  1. build_storyboard  → write storyboard.json
  2. preview_payload   → show the exact payload
  3. render_multiframe OR render_chained
  4. concat_shots (chained only)
  5. build_report

HARD RULE: the agent NEVER calls render_* without a fresh human approval
message. `enhancor_queue` is only reached after `--approve` is passed in the
agent's tool call arguments, and the agent's system prompt forbids synthesising
approval.

Usage:
  export ANTHROPIC_API_KEY=...
  pip install -r orchestrator/requirements.txt
  python orchestrator/storyboard_agent.py \
    --product my_product_slug --subject my_subject_slug \
    --shots 4 --duration 12 --aspect 9:16 --style ugc
"""

import argparse
import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL_DIR = REPO_ROOT / ".claude" / "skills" / "storyboard" / "scripts"

try:
    from claude_agent_sdk import (
        ClaudeAgentOptions,
        ClaudeSDKClient,
        create_sdk_mcp_server,
        tool,
    )
except ImportError:
    print(
        "claude_agent_sdk is not installed. Run: pip install -r orchestrator/requirements.txt",
        file=sys.stderr,
    )
    sys.exit(1)


def _run(cmd, cwd=None):
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd or REPO_ROOT)
    return {
        "returncode": r.returncode,
        "stdout": r.stdout.strip(),
        "stderr": r.stderr.strip(),
    }


def _text(s):
    return {"content": [{"type": "text", "text": s}]}


@tool(
    "build_storyboard",
    "Build a storyboard.json (beat sheet + per-shot prompts) from brand/registry context. Does NOT call the video API.",
    {
        "product": str,
        "subject": str,
        "shots": int,
        "duration": int,
        "aspect": str,
        "mode": str,  # "multi_frame" | "chained" | "auto"
        "style": str,  # ugc | cinematic | podcast | greenscreen
        "use_audio": bool,
    },
)
async def build_storyboard(args):
    cmd = [
        sys.executable,
        str(SKILL_DIR / "build_storyboard.py"),
        "--product", args["product"],
        "--subject", args.get("subject", ""),
        "--shots", str(args["shots"]),
        "--duration", str(args["duration"]),
        "--aspect", args.get("aspect", "9:16"),
        "--style", args.get("style", "ugc"),
    ]
    mode = args.get("mode", "auto")
    if mode in ("multi_frame", "chained"):
        cmd += ["--mode", mode]
    if args.get("use_audio"):
        cmd += ["--use-audio"]

    r = _run(cmd)
    if r["returncode"] != 0:
        return _text(f"build_storyboard FAILED:\n{r['stderr']}")
    sb_path = r["stdout"].splitlines()[-1]
    sb = json.loads(Path(sb_path).read_text())
    summary = f"Storyboard written to {sb_path}\n\n" + json.dumps(sb, indent=2)
    return _text(summary)


@tool(
    "preview_payload",
    "Preview the exact API payload(s) that will be sent, WITHOUT submitting. Must be shown to the user before any render_* call.",
    {"storyboard_path": str},
)
async def preview_payload(args):
    sb_path = args["storyboard_path"]
    sb = json.loads(Path(sb_path).read_text())
    if sb["mode"] == "multi_frame":
        r = _run([sys.executable, str(SKILL_DIR / "render_multiframe.py"),
                  "--storyboard", sb_path, "--dry-run"])
    else:
        r = _run([sys.executable, str(SKILL_DIR / "render_chained.py"),
                  "--storyboard", sb_path, "--dry-run"])
    if r["returncode"] != 0:
        return _text(f"preview_payload FAILED:\n{r['stderr']}")
    return _text(r["stdout"])


@tool(
    "render_multiframe",
    "Submit the storyboard as ONE multi_frame Enhancor call. Requires explicit human approval — set approve=true ONLY after the user has said yes. Polls until done.",
    {"storyboard_path": str, "webhook_url": str, "approve": bool},
)
async def render_multiframe(args):
    if not args.get("approve"):
        return _text("REFUSED: render_multiframe requires approve=true. Ask the user to approve the payload first.")
    cmd = [
        sys.executable, str(SKILL_DIR / "render_multiframe.py"),
        "--storyboard", args["storyboard_path"],
        "--webhook", args["webhook_url"],
        "--poll",
    ]
    r = _run(cmd)
    return _text(f"stdout:\n{r['stdout']}\n\nstderr:\n{r['stderr']}\n\nreturncode: {r['returncode']}")


@tool(
    "render_chained",
    "Submit the storyboard as N chained first_n_last_frames Enhancor calls. Requires approve=true. Polls each shot, extracts last frame, chains to next.",
    {"storyboard_path": str, "webhook_url": str, "approve": bool, "start_shot": int},
)
async def render_chained(args):
    if not args.get("approve"):
        return _text("REFUSED: render_chained requires approve=true. Ask the user to approve the payload first.")
    cmd = [
        sys.executable, str(SKILL_DIR / "render_chained.py"),
        "--storyboard", args["storyboard_path"],
        "--webhook", args["webhook_url"],
        "--start-shot", str(args.get("start_shot", 1)),
    ]
    r = _run(cmd)
    return _text(f"stdout:\n{r['stdout']}\n\nstderr:\n{r['stderr']}\n\nreturncode: {r['returncode']}")


@tool(
    "concat_shots",
    "Stitch chained shot MP4s into final.mp4 via ffmpeg. Only for chained mode.",
    {"storyboard_path": str, "reencode": bool},
)
async def concat_shots(args):
    cmd = [
        sys.executable, str(SKILL_DIR / "concat_shots.py"),
        "--storyboard", args["storyboard_path"],
    ]
    if args.get("reencode"):
        cmd.append("--reencode")
    r = _run(cmd)
    return _text(f"stdout:\n{r['stdout']}\n\nstderr:\n{r['stderr']}\n\nreturncode: {r['returncode']}")


@tool(
    "build_report",
    "Write an HTML report with the final video, each shot, and every prompt.",
    {"storyboard_path": str},
)
async def build_report(args):
    r = _run([sys.executable, str(SKILL_DIR / "build_report.py"),
              "--storyboard", args["storyboard_path"]])
    return _text(f"stdout:\n{r['stdout']}\n\nstderr:\n{r['stderr']}\n\nreturncode: {r['returncode']}")


@tool(
    "generate_webhook",
    "Create a webhook.site URL to receive the Enhancor completion callback. Uses $WEBHOOK_URL if set.",
    {},
)
async def generate_webhook(args):
    if os.environ.get("WEBHOOK_URL"):
        return _text(os.environ["WEBHOOK_URL"])
    r = _run(["curl", "-s", "-X", "POST", "https://webhook.site/token",
              "-H", "Accept: application/json"])
    if r["returncode"] != 0:
        return _text(f"generate_webhook FAILED:\n{r['stderr']}")
    try:
        uuid = json.loads(r["stdout"]).get("uuid")
        if uuid:
            return _text(f"https://webhook.site/{uuid}")
    except Exception as e:
        return _text(f"could not parse webhook response: {e}\n{r['stdout']}")
    return _text("webhook creation failed")


SYSTEM_PROMPT = """You are the Storyboard Orchestrator for the Seedance 2 UGC Ad Pipeline.

Your job: take brand + registry context and produce a multi-shot AI video ad.

HARD RULES (never violate):
1. ALWAYS call build_storyboard first, then show the full storyboard.json to the human.
2. ALWAYS call preview_payload next, show the output verbatim, and wait for explicit "approved" / "yes" / "go".
3. ONLY call render_multiframe or render_chained after receiving explicit human approval. When you do call them, set approve=true.
4. NEVER fabricate approval. If the user has not said yes, refuse to render.
5. For chained mode, after render_chained succeeds, call concat_shots, then build_report.
6. For multi_frame mode, after render_multiframe succeeds, call build_report.
7. Always include the API signup link when the user lacks an API key:
   https://app.enhancor.ai/api-dashboard — up to 65% off market price, cheapest Seedance 2 Full Access API, full face generation enabled.
8. If the registry contains audio, ASK the user whether to use it as the voice reference before building the storyboard.

Speak tersely. Show the user the JSON and the payload, then wait.
"""


async def run(argv):
    server = create_sdk_mcp_server(
        name="storyboard-tools",
        version="0.1.0",
        tools=[
            build_storyboard,
            preview_payload,
            render_multiframe,
            render_chained,
            concat_shots,
            build_report,
            generate_webhook,
        ],
    )

    options = ClaudeAgentOptions(
        system_prompt=SYSTEM_PROMPT,
        mcp_servers={"storyboard": server},
        allowed_tools=[
            "mcp__storyboard__build_storyboard",
            "mcp__storyboard__preview_payload",
            "mcp__storyboard__render_multiframe",
            "mcp__storyboard__render_chained",
            "mcp__storyboard__concat_shots",
            "mcp__storyboard__build_report",
            "mcp__storyboard__generate_webhook",
        ],
        permission_mode="acceptEdits",
        cwd=str(REPO_ROOT),
    )

    prompt_parts = [
        f"Build a storyboard for product='{argv.product}'",
    ]
    if argv.subject:
        prompt_parts.append(f"subject='{argv.subject}'")
    prompt_parts += [
        f"shots={argv.shots}",
        f"total_duration={argv.duration}s",
        f"aspect_ratio={argv.aspect}",
        f"style={argv.style}",
    ]
    if argv.mode != "auto":
        prompt_parts.append(f"force mode={argv.mode}")
    prompt_parts.append(
        "Call build_storyboard, then preview_payload, then stop and show me both. "
        "Wait for my explicit 'approved' before any render call."
    )
    prompt = ". ".join(prompt_parts)

    async with ClaudeSDKClient(options=options) as client:
        await client.query(prompt)
        async for msg in client.receive_response():
            print(msg)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--product", required=True)
    p.add_argument("--subject", default="")
    p.add_argument("--shots", type=int, default=4)
    p.add_argument("--duration", type=int, default=12)
    p.add_argument("--aspect", default="9:16")
    p.add_argument("--style", default="ugc", choices=["ugc", "cinematic", "podcast", "greenscreen"])
    p.add_argument("--mode", default="auto", choices=["auto", "multi_frame", "chained"])
    args = p.parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
