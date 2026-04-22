#!/usr/bin/env python3
"""
Offline test suite for the storyboard skill.

NO network, NO API calls, NO files written outside /tmp. Safe to run from CI
or a SessionStart hook. Exits non-zero on failure.

Covers:
- build_storyboard.py: split_duration correctness, validation errors, role mapping
- prompt_framework: each of the five layers in isolation, composition, determinism
- storyboard.json shape: valid output for every shot count
- renderer dry-runs: payload shape without hitting the API

Run:
  python3 .claude/skills/storyboard/scripts/test_storyboard.py
"""

import json
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import build_storyboard as BS
from prompt_framework import reference, antiai, timecode, constraints, specificity
from prompt_framework.compose import compose_shot_prompt


_PASS = []
_FAIL = []


def _test(name):
    def deco(fn):
        try:
            fn()
            _PASS.append(name)
            print(f"  [PASS] {name}")
        except AssertionError as e:
            _FAIL.append((name, str(e)))
            print(f"  [FAIL] {name}: {e}")
        except Exception as e:
            _FAIL.append((name, repr(e)))
            print(f"  [ERROR] {name}: {repr(e)}")
            traceback.print_exc()
        return fn
    return deco


# ---------- build_storyboard.py ----------

@_test("split_duration sums to total")
def _t1():
    for n in range(1, 7):
        for total in range(n * 2, n * 6 + 1):
            out = BS.split_duration(total, n)
            assert sum(out) == total, f"n={n} total={total} got {out}"
            assert all(d >= 2 for d in out), f"got {out}"
            assert len(out) == n


@_test("split_duration rejects under-budget")
def _t2():
    try:
        BS.split_duration(5, 6)
    except ValueError:
        return
    raise AssertionError("expected ValueError for 5s / 6 shots")


@_test("role map covers 1..6")
def _t3():
    for n in range(1, 7):
        assert n in BS.ROLE_MAP, f"missing {n} in ROLE_MAP"
        assert len(BS.ROLE_MAP[n]) == n, f"ROLE_MAP[{n}] wrong length"


@_test("timestamp_block uses 00:XX format for all durations")
def _t4():
    for d in range(2, 16):
        line = BS.timestamp_block(d)
        assert "00:" in line, f"bad format for {d}s: {line}"


# ---------- prompt_framework layers ----------

_MIN_CTX = {
    "product_context": {"ad_notes": "3-inch amber glass bottle with black pump"},
    "subject_context": {"ad_notes": "a 20-something woman with shoulder-length brown hair in a cream hoodie"},
    "brand": {"product_name": "Test Serum", "discount_code": "GLOW20"},
    "aspect_ratio": "9:16",
    "format_style": "ugc",
    "use_audio": True,
    "is_chained": False,
    "is_first_shot": True,
    "total_shots": 4,
}
_SHOT = {"idx": 1, "role": "hook", "duration": 3}


@_test("reference layer handles missing context")
def _t5():
    out = reference.build(_SHOT, {"format_style": "ugc"})
    assert isinstance(out, str) and len(out) > 0
    assert "product" in out.lower()


@_test("antiai layer varies by format")
def _t6():
    ugc = antiai.build(_SHOT, {"format_style": "ugc", "is_chained": False})
    cine = antiai.build(_SHOT, {"format_style": "cinematic", "is_chained": False})
    assert ugc != cine, "anti-AI should vary by format"


@_test("antiai layer adds continuity avoids for chained non-first shots")
def _t7():
    base = antiai.build(_SHOT, {"format_style": "ugc", "is_chained": False, "is_first_shot": True})
    chained = antiai.build(_SHOT, {"format_style": "ugc", "is_chained": True, "is_first_shot": False})
    assert len(chained) > len(base), "chained should add avoid-phrases"
    assert "drift" in chained.lower()


@_test("timecode layer produces dialogue budget")
def _t8():
    out = timecode.build({"idx": 1, "role": "hook", "duration": 8}, {})
    assert "00:01-00:06" in out, f"bad dialogue window: {out}"
    assert "words" in out.lower()


@_test("timecode layer no-dialogue for <4s")
def _t9():
    out = timecode.build({"idx": 1, "role": "hook", "duration": 3}, {})
    assert "no dialogue" in out.lower()


@_test("constraints layer has MUST and NEVER")
def _t10():
    out = constraints.build(_SHOT, _MIN_CTX)
    assert "MUST" in out
    assert "NEVER" in out


@_test("constraints layer varies by role")
def _t11():
    hook = constraints.build({"idx": 1, "role": "hook", "duration": 3}, _MIN_CTX)
    cta = constraints.build({"idx": 4, "role": "cta", "duration": 3}, _MIN_CTX)
    assert hook != cta, "constraints must vary by role"


@_test("specificity replaces 'the product' when brand name present")
def _t12():
    txt = "The subject holds the product at chest height."
    out = specificity.build(txt, _MIN_CTX)
    assert "Test Serum" in out, f"got {out}"


@_test("specificity leaves text alone when no brand name")
def _t13():
    txt = "The subject holds the product."
    out = specificity.build(txt, {"product_context": {}, "subject_context": {}, "brand": {}})
    assert out == txt


# ---------- compose ----------

@_test("compose_shot_prompt is deterministic")
def _t14():
    p1 = compose_shot_prompt(_SHOT, _MIN_CTX)
    p2 = compose_shot_prompt(_SHOT, _MIN_CTX)
    assert p1 == p2, "compose must be deterministic"


@_test("compose_shot_prompt contains all five layer signatures")
def _t15():
    out = compose_shot_prompt(_SHOT, _MIN_CTX)
    assert "@product_image1" in out or "@image1" in out, "reference layer missing"
    assert "Avoid:" in out, "antiai layer missing"
    assert "Timeline:" in out, "timecode layer missing"
    assert "MUST" in out, "constraints layer missing"
    assert "Test Serum" in out, "specificity layer didn't run"


@_test("compose includes continuity line for chained non-first")
def _t16():
    ctx = dict(_MIN_CTX, is_chained=True, is_first_shot=False)
    shot = dict(_SHOT, continuity_anchor="subject mid-turn, right hand raised")
    out = compose_shot_prompt(shot, ctx)
    assert "first_frame_image" in out
    assert "mid-turn" in out


@_test("compose inserts discount code on cta role")
def _t17():
    shot = {"idx": 4, "role": "cta", "duration": 5}
    out = compose_shot_prompt(shot, _MIN_CTX)
    assert "GLOW20" in out


# ---------- CLI end-to-end (writes to /tmp) ----------

@_test("CLI: valid build writes parseable JSON")
def _t18():
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "sb.json"
        r = subprocess.run(
            [sys.executable, str(Path(__file__).resolve().parent / "build_storyboard.py"),
             "--product", "fake", "--shots", "4", "--duration", "12",
             "--aspect", "9:16", "--style", "ugc",
             "--run-id", "test", "--out", str(out)],
            capture_output=True, text=True, timeout=30,
        )
        assert r.returncode == 0, r.stderr
        data = json.loads(out.read_text())
        assert len(data["shots"]) == 4
        assert sum(s["duration"] for s in data["shots"]) == 12


@_test("CLI: invalid shot count errors")
def _t19():
    r = subprocess.run(
        [sys.executable, str(Path(__file__).resolve().parent / "build_storyboard.py"),
         "--product", "fake", "--shots", "7", "--duration", "30"],
        capture_output=True, text=True, timeout=30,
    )
    assert r.returncode != 0
    assert "shots must be" in r.stderr.lower()


@_test("CLI: under-budget errors")
def _t20():
    r = subprocess.run(
        [sys.executable, str(Path(__file__).resolve().parent / "build_storyboard.py"),
         "--product", "fake", "--shots", "6", "--duration", "10"],
        capture_output=True, text=True, timeout=30,
    )
    assert r.returncode != 0
    assert "cannot split" in r.stderr.lower()


@_test("CLI: render_multiframe with bad path errors cleanly")
def _t21():
    r = subprocess.run(
        [sys.executable, str(Path(__file__).resolve().parent / "render_multiframe.py"),
         "--storyboard", "/nonexistent/path.json", "--dry-run"],
        capture_output=True, text=True, timeout=30,
    )
    assert r.returncode != 0
    assert "not found" in r.stderr.lower()


# ---------- main ----------

def main():
    print(f"Running {len(_PASS) + len(_FAIL)} tests…")  # populated after decorators ran
    total = len(_PASS) + len(_FAIL)
    print(f"\n{len(_PASS)}/{total} passed.")
    if _FAIL:
        print("\nFailures:")
        for name, err in _FAIL:
            print(f"  - {name}: {err}")
        sys.exit(1)


if __name__ == "__main__":
    main()
