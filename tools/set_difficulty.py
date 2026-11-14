"""set_difficulty(level): 1, 2 or 3, for agent-made speaking challenges only."""
from tools._common import level, tool

NAME = "set_difficulty"
SCHEMA = tool(
    NAME,
    "Set the child's level for speaking challenges: 1 = one word, 2 = a short phrase (2-4 words), "
    "3 = a longer phrase or full sentence. Move up after steady hits, down after repeated misses.",
    {"level": {"type": "integer", "enum": [1, 2, 3]}},
    ["level"],
)


def parse(raw: dict) -> int:
    return level(raw)
