"""Layer 5 — Specificity.

Post-processor: replace known-weak abstractions with concrete nouns from context.
Only replaces when a concrete replacement exists; never fabricates.

Pure function. No I/O.
"""

import re
from typing import Dict, Any, List, Tuple


def _nonempty(s: Any) -> str:
    return s.strip() if isinstance(s, str) and s.strip() else ""


def _subject_phrase(subject_ctx: Dict[str, Any]) -> str:
    notes = _nonempty(subject_ctx.get("ad_notes")) or _nonempty(subject_ctx.get("description"))
    return notes or ""


def _product_phrase(product_ctx: Dict[str, Any], brand: Dict[str, Any]) -> str:
    name = _nonempty(brand.get("product_name"))
    if name:
        return name
    return _nonempty(product_ctx.get("ad_notes")) or _nonempty(product_ctx.get("description"))


def _setting_phrase(product_ctx: Dict[str, Any], brand: Dict[str, Any]) -> str:
    return (
        _nonempty(product_ctx.get("setting"))
        or _nonempty(product_ctx.get("environment"))
        or _nonempty(brand.get("preferred_setting"))
    )


def _replacements(context: Dict[str, Any]) -> List[Tuple[re.Pattern, str]]:
    product = _product_phrase(context.get("product_context", {}) or {}, context.get("brand", {}) or {})
    subject = _subject_phrase(context.get("subject_context", {}) or {})
    setting = _setting_phrase(context.get("product_context", {}) or {}, context.get("brand", {}) or {})

    subs: List[Tuple[re.Pattern, str]] = []

    # Only add replacements when we have concrete strings to swap in.
    if product:
        subs.append((re.compile(r"\bthe product\b(?!\s*\()", re.IGNORECASE), product))
    if subject:
        subs.append((re.compile(r"\bthe subject\b(?!\s*\()", re.IGNORECASE), subject))
        subs.append((re.compile(r"\ba presenter on camera\b", re.IGNORECASE), subject))
    if setting:
        subs.append((re.compile(r"\ba clean, well-lit space\b", re.IGNORECASE), setting))

    return subs


def build(text: str, context: Dict[str, Any]) -> str:
    """Apply specificity replacements to the accumulated prompt."""
    for pat, repl in _replacements(context):
        # First match only per pattern, to avoid over-replacing when the word appears many times
        text = pat.sub(repl, text, count=1)
    return text
