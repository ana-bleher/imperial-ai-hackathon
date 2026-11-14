"""Tests never call the real Anthropic API. By default the agent 'fails' instantly, so every turn
uses the fallback rule; tests in test_tutor.py replace tutor.call_model with a fake."""
import pytest

from agent import tutor


@pytest.fixture(autouse=True)
def no_real_agent(monkeypatch):
    async def offline(messages):
        raise RuntimeError("no network in tests")
    monkeypatch.setattr(tutor, "call_model", offline)


@pytest.fixture(autouse=True)
def no_real_voice(monkeypatch):
    """Voice calls fail instantly in tests, so every response comes back without audio."""
    from tools import voice

    def offline(*args):
        raise RuntimeError("no network in tests")
    monkeypatch.setattr(voice, "transcribe", offline)
    monkeypatch.setattr(voice, "speak", offline)
