"""Shared helpers for the storyboard skill: paths, env, upload, Enhancor HTTP."""

import json
import os
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[4]
REGISTRY_PATH = BASE_DIR / "assets" / "registry.json"
BRANDS_PATH = BASE_DIR / "config" / "brands.json"
PROJECTS_DIR = BASE_DIR / "projects"
OUTPUTS_DIR = BASE_DIR / "assets" / "outputs"

try:
    from dotenv import load_dotenv
    load_dotenv(BASE_DIR / ".env")
except ImportError:
    pass

ENHANCOR_API_URL = os.environ.get(
    "ENHANCOR_API_URL",
    "https://apireq.enhancor.ai/api/enhancor-ugc-full-access/v1",
)
ENHANCOR_API_KEY = os.environ.get("ENHANCOR_API_KEY", "")

_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode = ssl.CERT_NONE


def load_json(path):
    with open(path) as f:
        return json.load(f)


def save_json(path, data):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def upload_image(path):
    """Images → tmpfiles.org; returns direct download URL."""
    if not path:
        return None
    if str(path).startswith("http"):
        return str(path)
    if not os.path.exists(path):
        print(f"  [upload] missing: {path}", file=sys.stderr)
        return None
    try:
        r = subprocess.run(
            ["curl", "-s", "-F", f"file=@{path}", "https://tmpfiles.org/api/v1/upload"],
            capture_output=True, text=True, timeout=120,
        )
        resp = json.loads(r.stdout)
        if resp.get("status") == "success":
            page = resp["data"]["url"]
            return page.replace("tmpfiles.org/", "tmpfiles.org/dl/", 1)
    except Exception as e:
        print(f"  [upload] error {path}: {e}", file=sys.stderr)
    return None


def upload_media(path):
    """Audio/video → uguu.se (tmpfiles too slow for media)."""
    if not path:
        return None
    if str(path).startswith("http"):
        return str(path)
    if not os.path.exists(path):
        print(f"  [upload] missing: {path}", file=sys.stderr)
        return None
    try:
        r = subprocess.run(
            ["curl", "-s", "-F", f"files[]=@{path}", "https://uguu.se/upload"],
            capture_output=True, text=True, timeout=180,
        )
        data = json.loads(r.stdout)
        files = data.get("files") or []
        if files and files[0].get("url"):
            return files[0]["url"]
    except Exception as e:
        print(f"  [upload] error {path}: {e}", file=sys.stderr)
    return None


def enhancor_queue(payload):
    """POST /queue. Returns requestId or None."""
    if not ENHANCOR_API_KEY:
        print("  [enhancor] ENHANCOR_API_KEY not set", file=sys.stderr)
        return None
    req = urllib.request.Request(
        f"{ENHANCOR_API_URL}/queue",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "x-api-key": ENHANCOR_API_KEY},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60, context=_SSL_CTX) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            if body.get("success"):
                return body.get("requestId")
            print(f"  [enhancor] queue error: {body}", file=sys.stderr)
    except urllib.error.HTTPError as e:
        print(f"  [enhancor] HTTP {e.code}: {e.read().decode('utf-8', 'replace')}", file=sys.stderr)
    except Exception as e:
        print(f"  [enhancor] {e}", file=sys.stderr)
    return None


def enhancor_status(request_id):
    """POST /status. Returns dict or None."""
    if not ENHANCOR_API_KEY or not request_id:
        return None
    req = urllib.request.Request(
        f"{ENHANCOR_API_URL}/status",
        data=json.dumps({"request_id": request_id}).encode("utf-8"),
        headers={"Content-Type": "application/json", "x-api-key": ENHANCOR_API_KEY},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30, context=_SSL_CTX) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"  [status] {e}", file=sys.stderr)
        return None


def poll_until_complete(request_id, timeout_s=1800, interval_s=20):
    """Poll /status until COMPLETED/FAILED or timeout. Returns final status dict."""
    deadline = time.time() + timeout_s
    last_status = None
    while time.time() < deadline:
        s = enhancor_status(request_id)
        if s:
            status = s.get("status")
            if status != last_status:
                print(f"  [poll] {request_id[:8]}… → {status}")
                last_status = status
            if status in ("COMPLETED", "FAILED"):
                return s
        time.sleep(interval_s)
    return {"status": "TIMEOUT", "request_id": request_id}


def download(url, dest_path):
    """Download a URL to dest_path via curl."""
    Path(dest_path).parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(
        ["curl", "-sSL", "-o", str(dest_path), url],
        capture_output=True, text=True, timeout=600,
    )
    return r.returncode == 0 and Path(dest_path).exists()


def ffmpeg_last_frame(video_path, out_png):
    """Extract final frame of video_path to out_png."""
    Path(out_png).parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(
        [
            "ffmpeg", "-y", "-sseof", "-0.1", "-i", str(video_path),
            "-vframes", "1", "-q:v", "2", str(out_png),
        ],
        capture_output=True, text=True, timeout=120,
    )
    return r.returncode == 0 and Path(out_png).exists()


def ensure_webhook(explicit=None):
    """Resolve webhook URL: explicit arg > $WEBHOOK_URL > new webhook.site token."""
    if explicit:
        return explicit
    env_url = os.environ.get("WEBHOOK_URL")
    if env_url:
        return env_url
    try:
        r = subprocess.run(
            ["curl", "-s", "-X", "POST", "https://webhook.site/token", "-H", "Accept: application/json"],
            capture_output=True, text=True, timeout=30,
        )
        token = json.loads(r.stdout)
        uuid = token.get("uuid")
        if uuid:
            return f"https://webhook.site/{uuid}"
    except Exception as e:
        print(f"  [webhook] {e}", file=sys.stderr)
    return "https://webhook.site/placeholder"


def registry_image_paths(slug_category, slug):
    """Return absolute paths for images under registry[slug_category][slug]."""
    if not REGISTRY_PATH.exists():
        return []
    reg = load_json(REGISTRY_PATH)
    bucket = reg.get(slug_category, {}).get(slug, {})
    return [str(BASE_DIR / img["path"]) for img in bucket.get("images", [])]


def registry_ai_context(slug_category, slug):
    """Return first image's ai_context dict, or {}."""
    if not REGISTRY_PATH.exists():
        return {}
    reg = load_json(REGISTRY_PATH)
    bucket = reg.get(slug_category, {}).get(slug, {})
    imgs = bucket.get("images", [])
    if imgs and imgs[0].get("ai_context"):
        return imgs[0]["ai_context"]
    return {}


def registry_audio_path():
    """Return absolute path of first audio asset, or None."""
    if not REGISTRY_PATH.exists():
        return None
    reg = load_json(REGISTRY_PATH)
    audio = reg.get("audio", {})
    slug = next(iter(audio), None)
    if not slug:
        return None
    imgs = audio[slug].get("images", [])
    if imgs:
        return str(BASE_DIR / imgs[0]["path"])
    return None
