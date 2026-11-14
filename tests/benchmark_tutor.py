"""Compare tutor prompts on synthetic turns; network calls require --live.

Run from the repository root:
  python tests/benchmark_tutor.py --baseline-ref ffaabce
  python tests/benchmark_tutor.py --baseline-ref ffaabce --live --repeats 2

Uses ANTHROPIC_API_KEY from the process environment, never reads .env, and never
stores transcripts or model-generated text in its report. No voice calls occur.
"""
import argparse
import asyncio
import hashlib
import json
import math
import os
from pathlib import Path
import statistics
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agent import fallback, tutor  # noqa: E402


def narration(scene):
    text = scene["narration"]
    for placeholder, value in {"CHILD_NAME": "Mia", "PET": "fox", "THEY": "she",
                               "THEM": "her", "THEIR": "her"}.items():
        text = text.replace("{" + placeholder + "}", value)
    return text


def session(scene, tries=0):
    state = {"child": {"child_name": "Mia", "pronouns": "she", "avatar": {"pet": "fox"}},
             "log": [], **fallback.new_session_state()}
    fallback.enter_scene(state, scene, narration(scene), exclude={"mia"})
    state["tries"] = tries
    return state


def cases(scenes):
    speaking = next(s for s in scenes if fallback.decision_type(s) is None and s.get("next"))
    question = next(s for s in scenes if fallback.decision_type(s) == fallback.SINGLE_CORRECT)
    branch = next(s for s in scenes if fallback.decision_type(s) == fallback.BRANCH_CHOICE)
    target = session(speaking)["challenge"]["target_words"][0]
    correct = question["decision"]["correct_word"]
    incorrect = next(o["word"] for o in question["decision"]["options"] if o["word"] != correct)
    limit = fallback.max_attempts(question)
    rows = [
        ("speaking_hit", speaking, target, 0, "hit", "advance", speaking.get("next")),
        ("speaking_miss", speaking, "banana", 0, "miss", "retry_with_hint", None),
        ("speaking_limit", speaking, "banana", fallback.max_attempts(speaking) - 1,
         "miss", "move_on", speaking.get("next")),
        ("quiz_hit", question, correct, 0, "hit", "advance", question.get("next")),
        ("quiz_miss", question, incorrect, 0, "miss", "retry_with_hint", None),
        ("quiz_limit", question, incorrect, limit - 1, "miss", "move_on", question.get("next")),
        ("unclear_choice", branch, "dinosaur", 0, "miss", "retry", None),
        ("first_silence", speaking, "", 0, "silence", "retry", None),
        ("private_input", speaking, "My address is Zorblax Street", 0,
         "miss", "retry_with_hint", None),
    ]
    if len(target) >= 4:
        rows.append(("speaking_approximation", speaking, target[:-1], 0,
                     "hit", "advance", speaking.get("next")))
    for index, option in enumerate(branch["branches"]):
        rows.append((f"branch_{index + 1}", branch, option["word"], 0,
                     "hit", "advance", option["next"]))
    return rows


def summarize(samples):
    if not samples:
        return {"requests": 0}
    timings = sorted(row["agent_ms"] for row in samples)
    usage_known = [row for row in samples if row["cache_read_input_tokens"] is not None]
    return {
        "requests": len(samples),
        "agent_ms_median": statistics.median(timings),
        "agent_ms_p95": timings[math.ceil(len(timings) * 0.95) - 1],
        "fallback_rate": sum(row["source"] == "fallback" for row in samples) / len(samples),
        "timeout_rate": sum((row["fallback_reason"] or "").startswith("agent took over")
                            for row in samples) / len(samples),
        "accepted_scenario_rate": sum(row["scenario_pass"] for row in samples) / len(samples),
        "cache_hit_rate": (sum(row["cache_read_input_tokens"] > 0 for row in usage_known)
                           / len(usage_known)) if usage_known else None,
        "usage_responses": len(usage_known),
        "token_totals": {field: (sum(row[field] for row in samples if row[field] is not None)
                                 if any(row[field] is not None for row in samples) else None)
                         for field in tutor.USAGE_FIELDS},
    }


async def compare(prompts, scenes, repeats):
    lookup = {scene["id"]: scene for scene in scenes}
    samples = []
    original_prompt = tutor.SYSTEM_PROMPT
    try:
        for repeat in range(repeats):
            for index, case in enumerate(cases(scenes)):
                name, scene, transcript, tries, result, action, destination = case
                # Alternate which prompt runs first to reduce order bias.
                order = list(prompts) if (repeat + index) % 2 == 0 else list(reversed(prompts))
                for variant in order:
                    tutor.SYSTEM_PROMPT = prompts[variant]
                    following = lookup.get(scene.get("next"))
                    next_narration = (narration(following) if following and
                                      fallback.decision_type(following) is None else None)
                    decision, meta = await tutor.decide(
                        session(scene, tries), scene, narration(scene), transcript,
                        next_narration=next_narration, name_words={"mia"},
                        vocab=set(fallback.words(json.dumps(scenes))) | {"mia", "fox"})
                    matches = (decision["result"] == result and decision["action"] == action
                               and decision["next_id"] == destination)
                    private_safe = "zorblax" not in " ".join(
                        str(decision.get(key) or "") for key in ("feedback", "reason", "parent_note")
                    ).lower()
                    samples.append({
                        "variant": variant, "case": name, "repeat": repeat + 1, **meta,
                        "decision_matches": matches,
                        "scenario_pass": matches and private_safe and meta["source"] == "agent",
                    })
    finally:
        tutor.SYSTEM_PROMPT = original_prompt
    return samples


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-ref", required=True, help="Git revision containing the original prompt")
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--live", action="store_true", help="Make billable model calls using synthetic turns")
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("--repeats must be positive")
    baseline = subprocess.run(
        ["git", "show", f"{args.baseline_ref}:prompts/story_agent.md"], cwd=ROOT,
        capture_output=True, encoding="utf-8", check=True).stdout
    prompts = {"baseline": baseline, "compact": tutor.SYSTEM_PROMPT}
    scenes = json.loads((ROOT / "data" / "story.json").read_text(encoding="utf-8"))["scenes"]
    report = {
        "status": "not_run", "model": tutor.MODEL, "model_timeout_s": tutor.TIMEOUT_S,
        "baseline_ref": args.baseline_ref,
        "prompts": {name: {"words": len(text.split()), "characters": len(text),
                           "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()}
                    for name, text in prompts.items()},
        "planned_requests": len(cases(scenes)) * len(prompts) * args.repeats,
        "note": "Synthetic tutor calls only; excludes speech latency; small-sample p95 is exploratory.",
    }
    if not args.live:
        report["reason"] = "Dry run: add --live to measure model calls."
    elif not os.getenv("ANTHROPIC_API_KEY"):
        report["reason"] = "ANTHROPIC_API_KEY is unavailable in the process environment; no calls made."
    else:
        report["samples"] = asyncio.run(compare(prompts, scenes, args.repeats))
        report["summaries"] = {variant: summarize([s for s in report["samples"] if s["variant"] == variant])
                               for variant in prompts}
        report["status"] = "measured"
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
