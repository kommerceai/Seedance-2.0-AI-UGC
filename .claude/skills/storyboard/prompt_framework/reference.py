"""Layer 1 — Reference deconstruction.

Surface structured facts from the asset registry into the prompt so the model
has concrete nouns to attach to, rather than generic "a product" / "a subject".

Pure function. No I/O.
"""

from typing import Dict, Any

_DEFAULT_POSE = "facing camera at chest height"
_DEFAULT_EXPRESSION = "natural, engaged"
_DEFAULT_SETTING = "a clean, well-lit space"
_DEFAULT_LIGHT = "soft, even light"


def _pick(ctx: Dict[str, Any], *keys: str, default: str = "") -> str:
    """Return first non-empty value for any of the given keys (dot-path supported)."""
    for k in keys:
        cur: Any = ctx
        for part in k.split("."):
            if not isinstance(cur, dict) or part not in cur:
                cur = None
                break
            cur = cur[part]
        if isinstance(cur, str) and cur.strip():
            return cur.strip()
    return default


def product_descriptor(product_ctx: Dict[str, Any], brand: Dict[str, Any]) -> str:
    """Deconstruct the product into a concrete noun phrase."""
    name = _pick(brand, "product_name", default="")
    category = _pick(brand, "product_category", "category", default="")
    notes = _pick(product_ctx, "ad_notes", "description", default="")
    parts = []
    if name:
        parts.append(f"the product ({name}" + (f", a {category}" if category else "") + ")")
    else:
        parts.append("the product")
    if notes:
        parts.append(f"described as: {notes}")
    return " ".join(parts)


def subject_descriptor(subject_ctx: Dict[str, Any]) -> str:
    """Deconstruct the subject into a concrete noun phrase with pose/expression/outfit if available."""
    notes = _pick(subject_ctx, "ad_notes", "description", default="")
    pose = _pick(subject_ctx, "pose", default=_DEFAULT_POSE)
    expression = _pick(subject_ctx, "expression", default=_DEFAULT_EXPRESSION)
    outfit = _pick(subject_ctx, "outfit", "clothing", default="")
    if notes:
        base = notes
    else:
        base = "the subject on camera"
    attrs = [f"pose: {pose}", f"expression: {expression}"]
    if outfit:
        attrs.append(f"outfit: {outfit}")
    return f"{base} ({', '.join(attrs)})"


def setting_descriptor(product_ctx: Dict[str, Any], brand: Dict[str, Any]) -> str:
    """Deconstruct the setting — location, lighting, environment."""
    setting = _pick(product_ctx, "setting", "environment", default="")
    light = _pick(product_ctx, "lighting", default=_DEFAULT_LIGHT)
    if not setting:
        setting = _pick(brand, "preferred_setting", default=_DEFAULT_SETTING)
    return f"{setting}, {light}"


def image_refs(format_style: str) -> str:
    """Return the @-reference syntax appropriate for the format."""
    if format_style == "ugc":
        return "@product_image1 (the product) and @influencer_image1 (the subject)"
    return "@image1 (product) and @image2 (subject)"


def build(shot: Dict[str, Any], context: Dict[str, Any]) -> str:
    """Compose the reference-deconstruction opening line for a shot."""
    product_ctx = context.get("product_context", {}) or {}
    subject_ctx = context.get("subject_context", {}) or {}
    brand = context.get("brand", {}) or {}
    fmt = context.get("format_style", "ugc")

    prod = product_descriptor(product_ctx, brand)
    subj = subject_descriptor(subject_ctx)
    setting = setting_descriptor(product_ctx, brand)
    refs = image_refs(fmt)

    return (
        f"Reference the images: {refs}. "
        f"Subject: {subj}. "
        f"Product: {prod}. "
        f"Setting: {setting}."
    )
