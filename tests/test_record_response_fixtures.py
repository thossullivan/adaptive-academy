"""scripts/record_response_fixtures.py spends money, so it must refuse to run without --live.

Only the offline paths are exercised here: the plan and estimate, the refusal, the
confirmation prompt, and the redaction. Nothing here reaches the API (the network guard in
conftest.py would fail the test if it tried).
"""

import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "record_response_fixtures.py"


@pytest.fixture
def script(monkeypatch):
    spec = importlib.util.spec_from_file_location("record_response_fixtures", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    # Registered first: its dataclasses resolve their annotations through sys.modules.
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)

    def _no_recording(*_a, **_kw):
        raise AssertionError("the recorder must not be built without --live and a yes")

    monkeypatch.setattr(module, "Recorder", _no_recording)
    monkeypatch.setattr(module.registry._settings.settings, "reasoning_model", "")
    return module


def test_without_live_it_prints_the_estimate_and_refuses(script, capsys, tmp_path):
    assert script.main(["--out", str(tmp_path)]) == 2
    out, err = capsys.readouterr()
    assert "Estimated cost: about $" in out and "at most $" in out
    assert "tutor_reply" in out and "research" in out
    assert "Refusing to call the API without --live" in err
    assert list(tmp_path.iterdir()) == []


def test_live_still_asks_and_a_no_sends_nothing(script, capsys, monkeypatch, tmp_path):
    monkeypatch.setattr("builtins.input", lambda _prompt: "n")
    assert script.main(["--live", "--out", str(tmp_path)]) == 1
    assert "Aborted. Nothing was sent." in capsys.readouterr().out
    assert list(tmp_path.iterdir()) == []


def test_estimate_scales_with_the_selection(script):
    model = "claude-sonnet-5-5"
    one = script.estimate(model, [s for s in script.SCENARIOS if s.name == "json_max_tokens"])
    every = script.estimate(model, script.SCENARIOS)
    assert 0 < one[0] <= one[1] < every[1]
    assert every[0] < every[1]


def test_redaction_keeps_references_and_hides_opaque_values(script):
    redact = script.Redactor()
    body = {
        "id": "msg_01AbC", "request_id": "req_123",
        "content": [
            {"type": "thinking", "thinking": "", "signature": "EqQBsecret=="},
            {"type": "server_tool_use", "id": "srvtoolu_01X", "name": "web_search",
             "input": {"query": "q"}},
            {"type": "web_search_tool_result", "tool_use_id": "srvtoolu_01X",
             "content": [{"type": "web_search_result", "url": "https://e.org",
                          "title": "t", "encrypted_content": "Eo0secret", "page_age": None}]},
        ],
    }
    out = redact(body)
    assert out["id"] == "msg_recorded0001" and out["request_id"] == "req_recorded_redacted"
    thinking, use, result = out["content"]
    assert thinking["signature"].startswith("recorded-signature-redacted-")
    assert thinking["thinking"] == ""  # empty stays empty
    assert use["id"] == result["tool_use_id"] == "srvtoolu_recorded0001"
    assert result["content"][0]["encrypted_content"].startswith("recorded-encrypted-content")
    assert result["content"][0]["url"] == "https://e.org" and use["input"] == {"query": "q"}
