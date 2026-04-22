# Five-Layer Prompt Framework

A pipeline for generating high-quality AI video ad prompts. Each layer is a pure function that takes a shot context and returns a text fragment; the final prompt is the composition of all five.

The layers, in order of composition:

| # | Layer | File | Purpose |
|---|-------|------|---------|
| 1 | Reference deconstruction | `reference.py` | Surface structured facts from the asset registry (pose, lighting, outfit, product orientation, setting) instead of generic nouns |
| 2 | Anti-AI steering | `antiai.py` | Append targeted avoid-phrases that push the model away from known AI artifacts (glass distortion, extra fingers, dead eyes, plastic skin, text mush, jump-cut smear) |
| 3 | Time-coded architecture | `timecode.py` | Per-shot timestamp block + dialogue budget (scales to each shot's duration) |
| 4 | Constraint engineering | `constraints.py` | Scene-level MUST/NEVER rules per format (label facing camera, hand visible, no mid-word cuts) |
| 5 | Specificity | `specificity.py` | Final polish — replace abstractions with concrete nouns/numbers/colors pulled from the registry |

## Why this order

1. **Reference first** — everything downstream needs concrete facts to attach to.
2. **Anti-AI second** — guards against the most common failure modes before we pile on other language.
3. **Timecode third** — structure before content.
4. **Constraints fourth** — scene-level guardrails, layered over the timed structure.
5. **Specificity last** — a polish pass that replaces any abstractions that slipped through earlier layers.

## Usage

```python
from prompt_framework.compose import compose_shot_prompt

prompt = compose_shot_prompt(
    shot={"idx": 1, "role": "hook", "duration": 3},
    total_shots=4,
    context={
        "product_context": {...},   # from assets/registry.json ai_context
        "subject_context": {...},
        "brand": {...},             # from config/brands.json
        "aspect_ratio": "9:16",
        "format_style": "ugc",
        "use_audio": True,
        "is_chained": False,
        "is_first_shot": True,
    },
)
```

Or via the skill — build_storyboard.py has a `--framework` flag that switches from the legacy one-pass prompt builder to the five-layer pipeline.

## Design rules

- Every layer is a **pure function**. No file I/O, no network, no global state. This is what makes the pipeline testable.
- Every layer returns a **string or list of strings**; compose concatenates them.
- Every layer **no-ops gracefully** when context is missing. Missing `product_context` → layer skips product-specific steering, doesn't crash.
- Every layer is **composable in isolation**. You can unit-test each layer with a fake shot dict.

## Per-layer reference

### 1. Reference deconstruction (`reference.py`)

Reads `context.product_context.ad_notes` and similar fields, returns a structured opening line:

> "The subject (pose: holding chest-height, outfit: cream hoodie, expression: surprised) holds the product (orientation: label forward, size: 3-inch amber glass bottle) under soft window light from camera-left."

If `ad_notes` is missing, falls back to generic template phrases.

### 2. Anti-AI steering (`antiai.py`)

Returns a short negative-constraint clause:

> "Avoid: plastic-looking skin, extra fingers, warped product text, glass distortion on the bottle, dead or vacant eyes, jump-cut smearing between segments, mismatched lighting on subject and background."

Pulls from a curated list keyed by format style (UGC vs cinematic vs greenscreen have different common artifacts).

### 3. Time-coded architecture (`timecode.py`)

Mirrors the existing `timestamp_block()` in build_storyboard.py — pulled out so it can be used standalone in tests. Given `duration`, emits:

> "Timeline for this shot: 00:00-00:01 silent opening, 00:01-00:05 dialogue window, 00:05-00:07 silent closing."

Plus dialogue word budget. `<4s` shots get a no-dialogue timeline.

### 4. Constraint engineering (`constraints.py`)

Scene-level MUST/NEVER lines, format-dependent:

> "MUST show the product label clearly forward at least once in this shot. MUST keep at least one hand visible on the product. NEVER cut mid-word. NEVER let the product leave frame before the final second."

UGC format emphasizes authenticity ("MUST show a small natural imperfection"). Cinematic emphasizes composition ("MUST place subject on a third"). Greenscreen emphasizes isolation ("NEVER show shadows on the backdrop").

### 5. Specificity (`specificity.py`)

Post-processor that scans the accumulated prompt and replaces known-weak tokens with concrete ones from context:

- "the product" → actual product name from `brand.product_name`
- "a subject" / "someone" → concrete subject descriptor from `subject_context`
- "a room" / "a setting" → concrete setting from `product_context.setting` if present

If no replacement available, leaves as-is — doesn't fabricate.

## Testing

```bash
python3 .claude/skills/storyboard/scripts/test_prompt_framework.py
```

Runs the per-layer pure-function tests — no API calls, no network, no files written outside `/tmp`.
