"""assess(result, reason): records "hit" or "miss" and why."""
from tools._common import text, tool

NAME = "assess"
SCHEMA = tool(
    NAME,
    "Record whether the child's answer to a speaking challenge is a hit or a miss, and why. "
    "A hit means most of the target words were said; accept reasonable pronunciation "
    "approximations (\"fowest\" for \"forest\"). The reason is for the parent dashboard: "
    "short, and never quotes the child's words.",
    {
        "result": {"type": "string", "enum": ["hit", "miss"]},
        "reason": {"type": "string", "description": "Short reason; never quote the child."},
    },
    ["result", "reason"],
)


def parse(raw: dict) -> dict:
    result = raw.get("result")
    if result not in ("hit", "miss"):
        raise ValueError("result must be hit or miss")
    return {"result": result, "reason": text(raw, "reason", 160)}
