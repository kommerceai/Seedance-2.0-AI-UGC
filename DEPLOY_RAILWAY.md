# Railway Deploy

The Control Center (`server.js`) is ready to run on Railway. Here's the fast path.

## 1. Required environment variables

Set these in **Railway → your service → Variables** before the first deploy.

| Var | Required? | What it does |
|---|---|---|
| `CONTROL_SECRET` | **Yes** for any public deploy | HTTP Basic Auth password. The browser will prompt for it. Without this, the Control Center runs open to anyone on the internet and will burn your API budget. |
| `CONTROL_USER` | Optional | Basic Auth username (default: `admin`). |
| `ENHANCOR_API_KEY` | Yes if using Enhancor | Your key from https://app.enhancor.ai/api-dashboard |
| `FAL_KEY` | Yes if using fal.ai | Your key from https://fal.ai/dashboard/keys |
| `STORYBOARD_PROVIDER` | Optional | `enhancor` (default) or `fal`. |
| `WEBHOOK_URL` | Optional | Public URL that receives provider callbacks. Once deployed, set this to `https://<your-service>.up.railway.app/api/webhook` if you add a webhook endpoint. |

**Do NOT commit keys to the repo.** They stay in Railway's Variables UI.

## 2. Persistent volume (important)

Railway serverless storage is ephemeral — uploads to `assets/` and generated videos in `projects/` vanish on each deploy unless you attach a volume.

In Railway: **your service → Settings → Volumes → + New Volume**:
- Mount path: `/app/assets`
- Size: start with 5 GB, raise later
- Repeat for `/app/projects` if you want generated videos to persist.

Without volumes, the Control Center will work but every upload resets on redeploy.

## 3. Deploy

You said Railway is synced to `creativeos`. Two paths depending on what that means:

**If Railway is already watching this GitHub repo:**
1. Merge `claude/ai-video-storyboards-xNF8i` into the branch Railway deploys (usually `main`), or
2. Point Railway at the `claude/ai-video-storyboards-xNF8i` branch under **Settings → Source → Branch**.

Railway auto-detects Node.js from `package.json`, runs `npm install`, starts `node server.js`, and exposes a public URL.

**If you're using the Railway CLI:**
```bash
npm i -g @railway/cli
railway login
railway link                  # pick the creativeos project
railway up                    # pushes the current directory
```

## 4. Verify

After deploy:
1. Railway gives you a URL like `https://seedance-xxxx.up.railway.app`.
2. Hit `https://<url>/healthz` — should return `ok` without prompting for auth.
3. Hit the root URL — browser prompts for Basic Auth. Enter the `CONTROL_USER`/`CONTROL_SECRET` you set.
4. Control Center loads. Upload a test asset → confirm it shows in Library.

## 5. What WON'T work out of the box on Railway

- **Storyboard chained rendering** needs `ffmpeg` for last-frame extraction. Nixpacks doesn't include it by default. To add it, create a `nixpacks.toml` in the repo root:
  ```toml
  [phases.setup]
  nixPkgs = ["nodejs_20", "ffmpeg"]
  ```
  Railway will rebuild with ffmpeg installed.
- **The storyboard skill itself** runs in your local Claude Code session, not on Railway. Only the Control Center (asset upload, registry, viewer) runs here.
- **Agent SDK orchestrator** (`orchestrator/storyboard_agent.py`) needs Python + `claude-agent-sdk`. If you want to run it as a Railway service, create a second Railway service pointing at the same repo with `startCommand: python orchestrator/storyboard_agent.py`.

## 6. Security checklist before you share the URL

- [ ] `CONTROL_SECRET` is set to a long random string
- [ ] `.env` is NOT in the deploy (confirmed by `.gitignore`)
- [ ] `ENHANCOR_API_KEY` / `FAL_KEY` are in Railway Variables, not source
- [ ] Volumes are attached for `/app/assets` and `/app/projects`
