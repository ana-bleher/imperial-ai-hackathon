"""next_step(action, say): what happens next, and the one warm sentence spoken to the child."""
from tools._common import text, tool

NAME = "next_step"
ACTIONS = ("advance", "retry_with_hint", "move_on")
SCHEMA = tool(
    NAME,
    "Choose what happens next and say ONE short, warm sentence to the child. "
    "advance = after a hit, go on with the story. retry_with_hint = stay on this scene and help. "
    "move_on = go on after a miss (when the attempts are used up). Call this on every turn.",
    {
        "action": {"type": "string", "enum": list(ACTIONS)},
        "say": {"type": "string",
                "description": "One short, warm sentence for a 4-6 year old. Never 'wrong'."},
    },
    ["action", "say"],
)


def parse(raw: dict) -> dict:
    action = raw.get("action")
    if action not in ACTIONS:
        raise ValueError(f"action must be one of {ACTIONS}")
    say = text(raw, "say", 160)
    if len(say.split()) > 25:
        raise ValueError("say is longer than one short sentence")
    if "wrong" in say.lower():
        raise ValueError("say must not tell the child they are wrong")
    return {"action": action, "say": say}
