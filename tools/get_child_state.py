"""get_child_state(session_id): level, words practised, recent hits and misses.

There is one model call per turn, so the model cannot wait for a tool result. Code calls this
before the model call and puts the result in the turn message instead of offering it as a tool.
"""


def get_child_state(sess: dict, recent: int = 5) -> dict:
    attempts = [e for e in sess["log"] if e["result"] in ("hit", "miss")][-recent:]
    return {
        "level": sess["level"],
        "words_practised": list(sess["practised"]),
        # Targets only, never the child's words.
        "recent": [{"scene": e["scene_id"], "result": e["result"], "targets": e["targets"]}
                   for e in attempts],
    }
