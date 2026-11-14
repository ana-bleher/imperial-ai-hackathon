"""notify_parent(note): a short note for the parent dashboard."""
from tools._common import text, tool

NAME = "notify_parent"
SCHEMA = tool(
    NAME,
    "Leave a short, practical note for the parent dashboard, e.g. \"Struggled with 'lantern' - "
    "practise together\". Use when a word was hard, or the child seemed upset or went off-topic. "
    "Never quote the child or include personal details.",
    {"note": {"type": "string"}},
    ["note"],
)


def parse(raw: dict) -> str:
    return text(raw, "note", 200)
