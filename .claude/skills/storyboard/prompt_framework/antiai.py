"""Layer 2 — Anti-AI steering.

Appends a targeted avoid-list to push the model away from known AI artifacts.
Format-dependent, since different styles fail in different ways.

Pure function. No I/O.
"""

from typing import Dict, Any

_COMMON = [
    "plastic-looking or waxy skin texture",
    "extra or missing fingers",
    "warped or illegible product label text",
    "dead, vacant, or asymmetric eyes",
    "mismatched lighting between subject and background",
]

_UGC = [
    "over-smooth cinematic grade (UGC should look authentic, not color-graded)",
    "camera stabilizer smoothness (this is shot handheld)",
    "studio-perfect framing (slight off-center is expected)",
]

_CINEMATIC = [
    "phone-camera artifacts (this is a cinematic shot)",
    "blown-out highlights on the product",
    "motion blur on the subject's face",
]

_PODCAST = [
    "distracting background motion",
    "more than two people in frame",
    "camera movement (this is a locked-off tripod shot)",
]

_GREENSCREEN = [
    "shadows falling on the backdrop",
    "color bleed from the backdrop onto the subject",
    "any non-backdrop background element",
]

_CHAINED = [
    "jump-cut smearing or morphing at the start of the shot",
    "subject identity drift (hair, facial structure, outfit must match the previous frame)",
    "product pose drift (the product must be in the exact position it was in at the handoff frame)",
]


def build(shot: Dict[str, Any], context: Dict[str, Any]) -> str:
    """Return the Avoid-phrase clause for this shot."""
    fmt = context.get("format_style", "ugc")
    is_chained = bool(context.get("is_chained"))
    is_first = bool(context.get("is_first_shot"))

    items = list(_COMMON)
    items += {
        "ugc": _UGC,
        "cinematic": _CINEMATIC,
        "podcast": _PODCAST,
        "greenscreen": _GREENSCREEN,
    }.get(fmt, _UGC)

    if is_chained and not is_first:
        items += _CHAINED

    return "Avoid: " + "; ".join(items) + "."
