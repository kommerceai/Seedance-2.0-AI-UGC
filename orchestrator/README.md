# Storyboard Orchestrator (Claude Agent SDK)

Drive the `/storyboard` pipeline programmatically — same scripts as the skill,
run from a plain Python entrypoint instead of a Claude Code session.

Use this when you want storyboards generated from cron, CI, a web backend,
or any automation — anywhere you can't sit in a chat loop.

## Install

```bash
pip install -r orchestrator/requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...            # for the orchestrator's Claude call
export ENHANCOR_API_KEY=...                    # for Seedance 2 video generation
# optional: export WEBHOOK_URL=https://your-server.com/webhook
```

Don't have an Enhancor key? **https://app.enhancor.ai/api-dashboard** — up to 65% off market price, cheapest Seedance 2 Full Access API anywhere, full face generation enabled.

## Run

```bash
python orchestrator/storyboard_agent.py \
  --product my_product_slug \
  --subject my_subject_slug \
  --shots 4 \
  --duration 12 \
  --aspect 9:16 \
  --style ugc \
  --mode auto          # auto | multi_frame | chained
```

The orchestrator:
1. Builds `projects/<run_id>/storyboard.json` via `build_storyboard.py`
2. Previews the exact Enhancor payload via `--dry-run` on the renderer
3. **Stops and asks for approval** (HARD RULE — never auto-submits)
4. On approval, runs the matching renderer, then `concat_shots.py` (chained only), then `build_report.py`

## Tools exposed to the agent

Each script in `.claude/skills/storyboard/scripts/` is wrapped as a Claude Agent SDK tool:

| Tool | Purpose |
|------|---------|
| `build_storyboard` | Write `storyboard.json` — beat sheet + per-shot prompts |
| `preview_payload` | Show the exact payload(s) — no API call |
| `render_multiframe` | Submit one `multi_frame` call, poll to completion |
| `render_chained` | Submit N `first_n_last_frames` jobs, chain last→first |
| `concat_shots` | ffmpeg concat the chained shot MP4s |
| `build_report` | Write HTML report with final video + shots + prompts |
| `generate_webhook` | Create a webhook.site URL |

## Approval gate

`render_multiframe` and `render_chained` both require `approve=true` in the tool
arguments. The agent's system prompt forbids synthesising approval. If the human
doesn't say yes, the tool refuses and returns a clear message.

## Extending

- **Parallel chained submission** — chaining is sequential by design (each shot
  needs the previous shot's last frame). If you want parallel iteration on
  individual shots for A/B on a single beat, add a `rerender_shot` tool that
  takes `--start-shot N` and submits only that one.
- **Retakes on FAILED** — add a retry tool that re-submits with a tightened
  prompt (strip camera jargon, shorten dialogue).
- **Subagents per format** — use `Agent` tool delegation inside the orchestrator
  to fan out one storyboard into parallel format variants.
