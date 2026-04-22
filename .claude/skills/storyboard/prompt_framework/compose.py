"""Compose all five layers into a final per-shot prompt.

Order matters: reference → anti-AI → timecode → constraints → specificity.
"""

from typing import Dict, Any

from . import reference, antiai, timecode, constraints, specificity


_ROLE_BODY = {
    "hook": "Open on a visual surprise. The subject reacts to the product with a quick, expressive gesture.",
    "product_reveal": "The subject deliberately lifts the product into clear frame with the label facing camera.",
    "demo": "The subject demonstrates using the product (opening, scooping, applying, pouring) with a close-in camera.",
    "proof": "The subject shows the result — real reaction, visible texture, or before/after moment.",
    "transformation": "A clear before/after within the shot; the subject transitions between two states in consistent framing.",
    "cta": "The subject holds the product up and delivers the call to action with direct eye contact.",
}


def _role_line(shot: Dict[str, Any], context: Dict[str, Any]) -> str:
    role = shot.get("role", "product_reveal")
    body = _ROLE_BODY.get(role, _ROLE_BODY["product_reveal"])

    # Discount code in CTA if available
    brand = context.get("brand", {}) or {}
    if role == "cta" and brand.get("discount_code"):
        body = body + f" Deliver the line with the discount code: {brand['discount_code']}."

    return f"SHOT {shot['idx']}/{context.get('total_shots', 1)} — {role} ({shot['duration']}s): {body}"


def _continuity_line(shot: Dict[str, Any], context: Dict[str, Any]) -> str:
    if not context.get("is_chained") or context.get("is_first_shot"):
        return ""
    anchor = shot.get("continuity_anchor", "")
    base = (
        "This shot begins from the keyframe provided as first_frame_image. "
        "Maintain exact continuity of subject pose, outfit, lighting, background, "
        "and product position from that frame."
    )
    if anchor:
        base += f" The action continues from: {anchor}"
    return base


def _audio_line(context: Dict[str, Any]) -> str:
    if not context.get("use_audio"):
        return ""
    return "Reference @audio1 as the exact voice, pacing, and emotional delivery. Always reference @audio1."


def compose_shot_prompt(shot: Dict[str, Any], context: Dict[str, Any]) -> str:
    """Run all five layers and produce the final prompt string for one shot."""
    parts = [
        _role_line(shot, context),
        reference.build(shot, context),
        antiai.build(shot, context),
        timecode.build(shot, context),
        constraints.build(shot, context),
        _continuity_line(shot, context),
        _audio_line(context),
        f"Camera aspect: {context.get('aspect_ratio', '9:16')}.",
    ]
    text = " ".join(p for p in parts if p)

    # Final layer: specificity polish
    text = specificity.build(text, context)

    return text
