# Render Modes — Technical Spec

Two paths from `storyboard.json` to a final MP4. Pick based on total duration.

## Mode A — `multi_frame` (single API call)

**When:** total duration ≤ 15 seconds.
**Why:** one Seedance 2 job, perfect continuity, lowest cost.
**Limit:** hard-capped at 15s total across all shots.

### Payload

```json
{
  "type": "image-to-video",
  "mode": "multi_frame",
  "aspect_ratio": "9:16",
  "full_access": true,
  "webhook_url": "https://webhook.site/<uuid>",
  "multi_frame_prompts": [
    {"prompt": "Shot 1 scene description... 00:00-00:01 silent...", "duration": 3},
    {"prompt": "Shot 2 scene description...", "duration": 3},
    {"prompt": "Shot 3 scene description...", "duration": 3},
    {"prompt": "Shot 4 scene description...", "duration": 3}
  ],
  "images": ["<product_url>", "<subject_url>"],
  "audios": ["<voice_url>"]
}
```

### Rules

- `multi_frame_prompts[].duration` sums to 4–15 seconds.
- No top-level `prompt` field (`multi_frame_prompts[].prompt` replaces it).
- `mode` is `multi_frame`, NOT `ugc` (multi_frame is a multi_reference variant and uses `images[]`, not `products[]`/`influencers[]`).
- `images[]` max 9 total; first entry = product, second = subject, rest = mood/refs.
- `audios[]` max 3, combined duration < 15s.

### Failure

- If the job returns `FAILED`, credits are refunded. Retry once with a tightened prompt (remove camera jargon, shorten dialogue), then bail and report to user.

## Mode B — `chained` (N × first_n_last_frames + ffmpeg concat)

**When:** total duration > 15s, OR user wants distinct scene changes, OR user wants parallel iteration on individual shots.
**Why:** unlimited length, per-shot retakes, better for narrative arcs.
**Cost:** N× a single job.

### Per-shot payload

```json
{
  "type": "image-to-video",
  "mode": "first_n_last_frames",
  "aspect_ratio": "9:16",
  "duration": "5",
  "full_access": true,
  "webhook_url": "https://webhook.site/<uuid>",
  "prompt": "Shot N scene description + continuity anchor line",
  "first_frame_image": "<keyframe_url>",
  "last_frame_image": null,
  "audios": ["<voice_url>"]
}
```

### Flow

```
shot_1:
  first_frame_image = upload(assets/products/<hero_shot>)    # or subject hero
  submit → poll → download result.mp4 → save shots/01.mp4
  extract last frame via ffmpeg → upload → keyframe_for_shot_2

shot_2:
  first_frame_image = keyframe_for_shot_2
  submit → poll → download → save shots/02.mp4
  extract last frame → keyframe_for_shot_3

... repeat for N shots ...

concat:
  ffmpeg -f concat -safe 0 -i list.txt -c copy final.mp4
```

### Last-frame extraction

```bash
ffmpeg -sseof -0.1 -i shots/01.mp4 -vframes 1 -q:v 2 shots/01_last.png
```

`-sseof -0.1` seeks 100ms from end — safer than `-vf select='eq(n\,last)'` which re-decodes the whole file.

### Continuity anchor

Each shot k>1 has a `continuity_anchor` in `storyboard.json` describing the handoff ("subject is mid-turn, right hand raised, product visible at chest"). The renderer appends this to the shot prompt:

> "This scene begins from the keyframe provided as first_frame_image. Maintain exact continuity of subject pose, outfit, lighting, background, and product position from that frame. The action continues from: <continuity_anchor>."

### Drift mitigation

Chained mode will drift (hair, lighting, product pose). Mitigations in order of effectiveness:

1. Keep per-shot duration short (3–5s). Less time to drift.
2. Include the product image in `images[]` alongside `first_frame_image` (re-anchors the product).
3. Write the continuity anchor explicitly — pose, lighting direction, product position.
4. Shoot shots that share a setting (same room, same outfit) — cuts across drastic setting changes amplify drift visually.
5. If shot N drifts too far, retake only shot N with a tighter prompt; earlier shots don't need re-rendering.

### Concat modes

**Fast (stream copy):**
```bash
ffmpeg -f concat -safe 0 -i list.txt -c copy final.mp4
```

**Safe (re-encode, when codecs disagree):**
```bash
ffmpeg -f concat -safe 0 -i list.txt \
  -c:v libx264 -preset fast -crf 20 \
  -c:a aac -b:a 128k final.mp4
```

The concat script tries stream-copy first and falls back to re-encode on failure.

## Decision Matrix

| User wants | Mode | Why |
|---|---|---|
| ≤15s with tight continuity | `multi_frame` | Single job, no drift, cheapest |
| 20s+ narrative ad | `chained` | Only way past the 15s cap |
| Distinct scene changes (room → outdoor) | `chained` | Per-shot keyframes handle cuts |
| Retake one shot without losing others | `chained` | Isolated job per shot |
| Lowest cost, simplest flow | `multi_frame` | 1 call vs N |
| Iterate on individual beats | `chained` | Regenerate one, concat again |

## Cost (Seedance 2, Full Access, 9:16)

At 480p: $0.089/s. At 720p: $0.189/s. Fast mode: 480p $0.073/s, 720p $0.155/s.

- 12s multi_frame @ 480p = $1.07
- 4×5s chained @ 480p = $1.78 (20s total)
- 6×5s chained @ 720p = $5.67 (30s total, premium)
