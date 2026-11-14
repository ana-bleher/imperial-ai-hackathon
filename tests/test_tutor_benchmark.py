"""Benchmark reporting must distinguish missing usage, fallback and live output."""
import json
from types import SimpleNamespace

import pytest

import benchmark_tutor as benchmark


def test_summary_reports_timeouts_and_unknown_usage_separately():
    usage = dict.fromkeys(benchmark.tutor.USAGE_FIELDS)
    rows = [
        {**usage, "agent_ms": 100, "source": "agent", "fallback_reason": None,
         "scenario_pass": True, "input_tokens": 30, "output_tokens": 20,
         "cache_creation_input_tokens": 0, "cache_read_input_tokens": 900},
        {**usage, "agent_ms": 6000, "source": "fallback", "fallback_reason": "agent took over 6s",
         "scenario_pass": False},
    ]
    summary = benchmark.summarize(rows)
    assert summary["agent_ms_median"] == 3050
    assert summary["agent_ms_p95"] == 6000
    assert summary["fallback_rate"] == summary["timeout_rate"] == 0.5
    assert summary["accepted_scenario_rate"] == 0.5
    assert summary["usage_responses"] == 1 and summary["cache_hit_rate"] == 1
    assert summary["token_totals"]["output_tokens"] == 20


def test_summary_with_no_cache_information_does_not_claim_cache_misses():
    row = {**dict.fromkeys(benchmark.tutor.USAGE_FIELDS), "agent_ms": 100,
           "source": "agent", "fallback_reason": None, "scenario_pass": True}
    summary = benchmark.summarize([row])
    assert summary["cache_hit_rate"] is None and summary["usage_responses"] == 0
    assert all(value is None for value in summary["token_totals"].values())
    assert benchmark.summarize([]) == {"requests": 0}


@pytest.mark.parametrize("live", [False, True])
def test_cli_does_not_call_model_without_live_flag_and_credentials(monkeypatch, capsys, live):
    argv = ["benchmark_tutor.py", "--baseline-ref", "example"] + (["--live"] if live else [])
    monkeypatch.setattr(benchmark.sys, "argv", argv)
    monkeypatch.setattr(benchmark.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(stdout="baseline"))
    monkeypatch.setattr(benchmark.os, "getenv", lambda name: None if live else "configured")
    monkeypatch.setattr(benchmark, "compare", lambda *args: pytest.fail("unexpected model comparison"))
    benchmark.main()
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "not_run" and "samples" not in report
    assert report["planned_requests"] > 0
