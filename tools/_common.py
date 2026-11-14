"""Shared helpers for the tutor agent's tools. Each tool file defines SCHEMA (sent to the model)
and parse(raw) -> cleaned value (raises ValueError on anything outside the limits)."""


def tool(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {
        "name": name,
        "description": description,
        "strict": True,
        "input_schema": {"type": "object", "properties": properties,
                         "required": required, "additionalProperties": False},
    }


def text(raw, field: str, max_len: int) -> str:
    value = raw.get(field) if isinstance(raw, dict) else None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    value = " ".join(value.split())
    if len(value) > max_len:
        raise ValueError(f"{field} longer than {max_len} characters")
    return value


def level(raw, field: str = "level") -> int:
    value = raw.get(field) if isinstance(raw, dict) else None
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 3:
        raise ValueError(f"{field} must be 1, 2 or 3")
    return value
