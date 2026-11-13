"""Check that each API key in .env works. Never prints the keys themselves.

Run from the repo root with the venv active:
    python check_keys.py
"""
import os

from dotenv import load_dotenv

load_dotenv()


def short(err: Exception) -> str:
    msg = str(err).replace("\n", " ")
    return f"{type(err).__name__}: {msg[:160]}"


def check_anthropic():
    import anthropic

    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY
    client.messages.create(
        model="claude-haiku-5-5",
        max_tokens=5,
        messages=[{"role": "user", "content": "Say ok"}],
    )


def check_tavily():
    from tavily import TavilyClient

    TavilyClient(api_key=os.getenv("TAVILY_API_KEY")).search("test", max_results=1)


def check_e2b():
    from e2b_code_interpreter import Sandbox

    sbx = Sandbox.create() if hasattr(Sandbox, "create") else Sandbox()  # reads E2B_API_KEY
    try:
        result = sbx.run_code("print(1 + 1)")
        if result.error:
            raise RuntimeError(result.error)
    finally:
        sbx.kill()


CHECKS = [
    ("Anthropic", "ANTHROPIC_API_KEY", check_anthropic),
    ("Tavily", "TAVILY_API_KEY", check_tavily),
    ("E2B", "E2B_API_KEY", check_e2b),
]

if __name__ == "__main__":
    for name, var, fn in CHECKS:
        if not os.getenv(var):
            print(f"⬜ {name}: {var} is empty in .env")
            continue
        try:
            fn()
            print(f"✅ {name}: working")
        except Exception as e:  # noqa: BLE001
            hint = ""
            if name == "Anthropic" and "credit" in str(e).lower():
                hint = " (key is fine, account needs credits)"
            print(f"❌ {name}: {short(e)}{hint}")
