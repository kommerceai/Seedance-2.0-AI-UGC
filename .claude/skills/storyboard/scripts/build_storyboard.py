#!/usr/bin/env python3
"""
build_storyboard.py — Turn brand + registry context into a storyboard.json.

Writes a beat sheet (hook/reveal/proof/cta by default) of N shots with per-shot
durations that sum to total_duration. Prompts are written with the same
timestamp discipline as ab-test-pipeline: silent 00:00-00:01, dialogue window,
silent last 2s — scaled to each shot.

Does NOT reconstruct the proprietary prompt templates at gateway.sirioberati.com
— shot prompts here are fresh scene descriptions generated from registry ai_context
and brand profile notes.

Usage:
  python3 build_storyboard.py \
    --product <product_slug> --subject <subject_slug> \
    --shots 4 --duration 12 --aspect 9:16 --mode multi_frame \
    --style ugc --out projects/<run_id>/storyboard.json
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _common import (
    BASE_DIR, BRANDS_PATH, PROJECTS_DIR,
    load_json, save_json,
    registry_image_paths, registry_ai_context, registry_audio_path,
)
from prompt_framework.compose import compose_shot_prompt

DEFAULT_ROLES = ["hook", "product_reveal", "proof", "cta"]
ROLES_1 = ["cta"]
ROLES_2 = ["hook", "cta"]
ROLES_3 = ["hook", "product_reveal", "cta"]
ROLES_5 = ["hook", "product_reveal", "proof", "transformation", "cta"]
ROLES_6 = ["hook", "product_reveal", "demo", "proof", "transformation", "cta"]

ROLE_MAP = {1: ROLES_1, 2: ROLES_2, 3: ROLES_3, 4: DEFAULT_ROLES, 5: ROLES_5, 6: ROLES_6}

MIN_SHOT_DURATION = 2
MAX_SHOTS = 6


def split_duration(total, n):
    """Split total seconds into n per-shot durations; each >= MIN_SHOT_DURATION, sum == total."""
    if n <= 0:
        return []
    if total < n * MIN_SHOT_DURATION:
        raise ValueError(
            f"cannot split {total}s into {n} shots of at least {MIN_SHOT_DURATION}s each "
            f"(need at least {n * MIN_SHOT_DURATION}s)"
        )
    base = total // n
    durations = [base] * n
    remainder = total - sum(durations)
    for i in range(remainder):
        durations[i % n] += 1
    assert sum(durations) == total, f"split_duration broke: {durations} != {total}"
    assert all(d >= MIN_SHOT_DURATION for d in durations)
    return durations


def timestamp_block(duration):
    """Return the standard timestamp line for a single shot of `duration` seconds."""
    if duration < 4:
        return f"Timeline for this shot: 00:00-00:{duration:02d} visual action, no dialogue."
    end = duration
    dialogue_end = max(1, end - 2)
    return (
        f"Timeline for this shot: 00:00-00:01 silent opening, "
        f"00:01-00:{dialogue_end:02d} dialogue window, "
        f"00:{dialogue_end:02d}-00:{end:02d} silent closing."
    )


def max_words(duration):
    """Dialogue budget: (duration - 3) * 2.5 words, floor 0."""
    return max(0, int((duration - 3) * 2.5))


def build_shot_prompt(role, duration, idx, total_shots, ctx, style, use_audio, is_chained, is_first_shot):
    """
    Build a per-shot prompt string. Fresh scene description — no template
    reconstruction. Uses registry ai_context and brand info.
    """
    product = ctx.get("product_context", {})
    subject = ctx.get("subject_context", {})
    brand = ctx.get("brand", {})

    product_desc = product.get("ad_notes") or product.get("description") or "the product"
    subject_desc = subject.get("ad_notes") or subject.get("description") or "a presenter on camera"
    discount = brand.get("discount_code")

    # Image reference syntax differs by mode/style
    if style == "ugc":
        img_refs = "@product_image1 and @influencer_image1"
    else:
        img_refs = "@image1 (product) and @image2 (subject)"

    # Camera style per format
    camera = {
        "ugc": "handheld iPhone selfie style, slight natural shake",
        "cinematic": "smooth gimbal tracking shot, cinematic color grade",
        "podcast": "locked-off studio tripod, soft key light, shallow depth of field",
        "greenscreen": "locked-off direct-to-camera, flat even lighting on a solid backdrop",
    }.get(style, "handheld iPhone selfie style")

    wbudget = max_words(duration)

    role_lines = {
        "hook": (
            f"Open with a visual hook: the subject shown in {img_refs} reacts to the product with a quick expressive gesture. "
            f"No product in frame until 00:01 — build curiosity first. "
            + (f'Spoken dialogue (<= {wbudget} words): "Wait til you see this."' if wbudget >= 4 else "No dialogue.")
        ),
        "product_reveal": (
            f"The subject in {img_refs} lifts the product into clear frame, holding it at chest height with the label facing camera. "
            f"Describe the product exactly: {product_desc}. "
            + (f'Spoken dialogue (<= {wbudget} words): name the product and one killer benefit.' if wbudget >= 6 else "No dialogue — let the visuals sell it.")
        ),
        "demo": (
            f"The subject in {img_refs} demonstrates using the product (opening, scooping, applying, pouring — choose based on {product_desc}). "
            f"Close camera on the action. "
            + (f"Spoken dialogue (<= {wbudget} words): one-sentence how-to." if wbudget >= 6 else "No dialogue — the action speaks.")
        ),
        "proof": (
            f"The subject in {img_refs} shows the result or reaction — genuine surprise, visible texture, or before/after moment. "
            f"Hold eye contact with the camera. "
            + (f"Spoken dialogue (<= {wbudget} words): a real reaction line." if wbudget >= 5 else "No dialogue — reaction sells.")
        ),
        "transformation": (
            f"Visual before/after or process cut: the subject in {img_refs} transitions between two states. "
            f"Use consistent framing so the change reads clearly. "
            + (f"Spoken dialogue (<= {wbudget} words): name the change." if wbudget >= 4 else "No dialogue.")
        ),
        "cta": (
            f"The subject in {img_refs} delivers the call to action: product held up, direct eye contact with camera. "
            + (
                f'Spoken dialogue (<= {wbudget} words): "Use code {discount}." ' if discount and wbudget >= 4
                else (f'Spoken dialogue (<= {wbudget} words): "Go grab yours."' if wbudget >= 3 else "No dialogue — hold a confident final look.")
            )
        ),
    }

    body = role_lines.get(role, role_lines["product_reveal"])

    parts = [
        f"SHOT {idx}/{total_shots} ({role}, {duration}s): {body}",
        f"Subject description: {subject_desc}.",
        f"Camera: {camera}. Aspect: {ctx['aspect_ratio']}.",
        timestamp_block(duration),
    ]

    if is_chained and not is_first_shot:
        parts.append(
            "This scene begins from the keyframe provided as first_frame_image. "
            "Maintain exact continuity of subject pose, outfit, lighting, background, "
            "and product position from that frame."
        )

    if use_audio:
        parts.append("Reference @audio1 as the exact voice, pacing, and emotional delivery. Always reference @audio1.")

    return " ".join(parts)


def choose_mode(total_duration, explicit_mode):
    if explicit_mode:
        return explicit_mode
    return "multi_frame" if total_duration <= 15 else "chained"


def build(args):
    ctx = {"aspect_ratio": args.aspect}

    # Brand context
    if BRANDS_PATH.exists():
        brands = load_json(BRANDS_PATH)
        brand_data = brands.get("brands", {}).get(args.product, {})
        if not brand_data and brands.get("brands"):
            brand_data = next(iter(brands["brands"].values()))
        ctx["brand"] = brand_data

    # Registry context
    ctx["product_context"] = registry_ai_context("products", args.product)
    ctx["subject_context"] = registry_ai_context("subjects", args.subject) if args.subject else {}

    product_paths = registry_image_paths("products", args.product)
    subject_paths = registry_image_paths("subjects", args.subject) if args.subject else []
    mood_paths = registry_image_paths("moods", args.mood) if args.mood else []
    audio_path = registry_audio_path() if args.use_audio else None

    mode = choose_mode(args.duration, args.mode)
    is_chained = mode == "chained"

    # Enforce shot count bounds
    if args.shots < 1 or args.shots > MAX_SHOTS:
        print(f"ERROR: shots must be 1..{MAX_SHOTS}, got {args.shots}", file=sys.stderr)
        sys.exit(2)

    # Enforce duration limits per mode
    if mode == "multi_frame" and not (4 <= args.duration <= 15):
        print(f"ERROR: multi_frame requires total duration 4-15s, got {args.duration}", file=sys.stderr)
        sys.exit(2)
    if is_chained and args.duration < 8:
        print(f"ERROR: chained mode requires at least 8s total, got {args.duration}", file=sys.stderr)
        sys.exit(2)

    roles = ROLE_MAP[args.shots]
    try:
        durations = split_duration(args.duration, args.shots)
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(2)

    shots = []
    for i, (role, dur) in enumerate(zip(roles, durations)):
        shot = {"idx": i + 1, "role": role, "duration": dur}
        if is_chained and i > 0:
            shot["continuity_anchor"] = (
                f"subject in a {role.replace('_', ' ')} pose, product in frame, "
                "consistent lighting and outfit from the previous shot."
            )

        if args.legacy_prompts:
            prompt = build_shot_prompt(
                role=role, duration=dur, idx=i + 1, total_shots=args.shots,
                ctx=ctx, style=args.style, use_audio=bool(audio_path),
                is_chained=is_chained, is_first_shot=(i == 0),
            )
        else:
            framework_ctx = {
                **ctx,
                "total_shots": args.shots,
                "format_style": args.style,
                "use_audio": bool(audio_path),
                "is_chained": is_chained,
                "is_first_shot": (i == 0),
            }
            prompt = compose_shot_prompt(shot, framework_ctx)

        shot["prompt"] = prompt
        shots.append(shot)

    run_id = args.run_id or f"sb_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"

    storyboard = {
        "run_id": run_id,
        "created_at": datetime.utcnow().isoformat() + "Z",
        "mode": mode,
        "format_style": args.style,
        "aspect_ratio": args.aspect,
        "resolution": args.resolution,
        "total_duration": args.duration,
        "shots": shots,
        "assets": {
            "products": product_paths,
            "influencers": subject_paths,
            "moods": mood_paths,
            "audio": audio_path,
        },
        "brand": ctx.get("brand", {}),
    }

    out_path = Path(args.out) if args.out else PROJECTS_DIR / run_id / "storyboard.json"
    save_json(out_path, storyboard)
    print(str(out_path))
    return out_path


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--product", required=True, help="product slug in assets/registry.json")
    p.add_argument("--subject", help="subject slug")
    p.add_argument("--mood", help="mood slug")
    p.add_argument("--shots", type=int, default=4)
    p.add_argument("--duration", type=int, default=12, help="total seconds")
    p.add_argument("--aspect", default="9:16")
    p.add_argument("--resolution", default="480p", choices=["480p", "720p"])
    p.add_argument("--mode", choices=["multi_frame", "chained"], help="override auto-pick")
    p.add_argument("--style", default="ugc", choices=["ugc", "cinematic", "podcast", "greenscreen"])
    p.add_argument("--use-audio", action="store_true")
    p.add_argument("--legacy-prompts", action="store_true",
                   help="Use the original single-pass prompt builder instead of the 5-layer framework.")
    p.add_argument("--run-id")
    p.add_argument("--out")
    args = p.parse_args()
    build(args)


if __name__ == "__main__":
    main()
