"""Layer 4 — Constraint engineering.

Scene-level MUST/NEVER rules per format + per role. Different from anti-AI:
this is "what the scene needs to show", not "what the model shouldn't do".

Pure function. No I/O.
"""

from typing import Dict, Any, List

_FORMAT_MUSTS = {
    "ugc": [
        "MUST feel handheld and real — slight natural movement is good",
        "MUST show the subject's face in at least two-thirds of this shot",
        "MUST keep the product in a believable on-hand position (not floating, not cut off)",
    ],
    "cinematic": [
        "MUST place the subject on a rule-of-thirds line",
        "MUST use smooth camera motion — a dolly, push-in, or slow arc",
        "MUST emphasize texture and depth through lighting",
    ],
    "podcast": [
        "MUST keep the camera locked-off (no zoom, no pan)",
        "MUST show 1-2 people in a consistent framing for the full shot",
        "MUST keep the product visible as a recurring prop, not a hero",
    ],
    "greenscreen": [
        "MUST keep the subject centered against a solid-color backdrop",
        "MUST keep sharp, isolated edges on the subject (clean key)",
        "MUST keep lighting flat and even across the subject",
    ],
}

_FORMAT_NEVERS = {
    "ugc": [
        "NEVER let the shot look like a polished commercial",
        "NEVER have the subject disappear from frame",
    ],
    "cinematic": [
        "NEVER use a phone-camera look",
        "NEVER let dialogue overlap with camera motion start/stop",
    ],
    "podcast": [
        "NEVER cut mid-conversation — dialogue must complete within this shot",
        "NEVER introduce a new person partway through",
    ],
    "greenscreen": [
        "NEVER cast any shadow onto the backdrop",
        "NEVER let any other object intrude into the frame",
    ],
}

_ROLE_MUSTS = {
    "hook": ["MUST create visual surprise in the first second"],
    "product_reveal": [
        "MUST show the product label facing camera for at least one second",
        "MUST have the subject deliberately lift or present the product",
    ],
    "demo": [
        "MUST show a clear hand-on-product action (opening, scooping, pouring, applying)",
        "MUST keep at least one hand visible throughout",
    ],
    "proof": [
        "MUST show a real-looking reaction on the subject's face",
        "MUST hold the beat long enough to read (no snap cuts in this shot)",
    ],
    "transformation": [
        "MUST show a clear before and after within the shot",
        "MUST keep the subject's framing consistent across the transition",
    ],
    "cta": [
        "MUST end with the product held up and the subject making eye contact with camera",
    ],
}

_UNIVERSAL_NEVERS = [
    "NEVER cut the subject mid-word",
    "NEVER let the product leave frame in the final 1 second",
    "NEVER show a hand holding the product in a physically implausible grip",
]


def _fmt(items: List[str]) -> str:
    return " ".join(x + "." for x in items)


def build(shot: Dict[str, Any], context: Dict[str, Any]) -> str:
    fmt = context.get("format_style", "ugc")
    role = shot.get("role", "product_reveal")

    musts = list(_FORMAT_MUSTS.get(fmt, _FORMAT_MUSTS["ugc"]))
    musts += _ROLE_MUSTS.get(role, [])
    nevers = list(_FORMAT_NEVERS.get(fmt, _FORMAT_NEVERS["ugc"]))
    nevers += _UNIVERSAL_NEVERS

    return _fmt(musts) + " " + _fmt(nevers)
