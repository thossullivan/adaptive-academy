"""The grading eval's runner (evals/grading/run_eval.py), end to end with no live model.

The runner is the one piece that can spend money, so the tests pin its refusals (no --live,
an app database as the scratch file, the daily limit) and run it end to end with an injected
scripted client: the prompt it sends is the app's, the caps it applies are the app's, usage
lands in the scratch database, and the report has every number the README promises.
"""

import json
import os
import shutil
import sqlite3
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evals.grading import run_eval  # noqa: E402
from evals.grading.case_file import load_cases  # noqa: E402

from adaptive_academy.engine.assess import grade_request  # noqa: E402
from adaptive_academy.llm import usage as llm_usage  # noqa: E402
from adaptive_academy.llm.scripted_client import ScriptedLLMClient  # noqa: E402
from adaptive_academy.llm.types import LLMResponse  # noqa: E402

CASES_FILE = ROOT / "evals" / "grading" / "cases.jsonl"


def _line(cid, *, band="high", missing=(), committed=(), answer="an answer") -> str:
    return json.dumps({
        "id": cid, "concept": "gradient descent", "kind": "self_explanation",
        "category": "correct", "criteria": ["explains the update"],
        "required": ["negative gradient", "learning rate"],
        "misconceptions": ["always global minimum"], "reference": "", "answer": answer,
        "truth": {"band": band, "missing_required": list(missing),
                  "misconceptions_committed": list(committed), "rationale": "r"},
    })


def _grade(score=0.9, *, mechanism=True, missing=(), committed=()) -> LLMResponse:
    return LLMResponse(text=json.dumps({
        "score": score, "mechanism_present": mechanism, "verdict": "v",
        "gaps": [] if score >= 0.9 else ["a gap"], "missing_required": list(missing),
        "misconceptions_committed": list(committed)}), stop_reason="end_turn")


class _BilledClient(ScriptedLLMClient):
    """A scripted client that records usage like the real one (llm/usage.record_usage)."""

    def complete(self, system, messages, tools):
        resp = super().complete(system, messages, tools)
        llm_usage.record_usage(
            backend="anthropic", model="claude-sonnet-5-5", role="reasoning",
            operation="complete",
            usage=SimpleNamespace(input_tokens=1000, output_tokens=100))
        return resp


@pytest.fixture
def small_cases(tmp_path):
    path = tmp_path / "cases.jsonl"
    path.write_text("\n".join([
        _line("hi"),                                            # correct: graded 0.9
        _line("fluent", band="low", missing=["learning rate"]),  # weak: graded high
        _line("capped"),                                         # correct, falsely capped
        _line("thin", band="medium", answer="short"),            # no mechanism: 0.9 -> 0.5
        _line("broken", band="low", missing=["negative gradient", "learning rate"]),
    ]) + "\n", encoding="utf-8")
    return path


def _args(tmp_path, cases, *extra):
    return run_eval.parse_args(["--cases", str(cases), "--out-dir", str(tmp_path / "out"),
                                "--scratch-db", str(tmp_path / "scratch" / "usage.db"),
                                *extra])


def _run(args, **kwargs):
    """run() in this process, where tests/_isolated_env.py already pointed the app's database
    at a temp directory before the app was imported (so the runner's own isolation, which
    must run before that import, is skipped)."""
    return run_eval.run(args, isolated=True, **kwargs)


def _responses():
    return [
        _grade(0.9),
        _grade(0.9),
        _grade(0.5, committed=["always global minimum"]),
        _grade(0.9, mechanism=False),
        LLMResponse(text="not json", stop_reason="end_turn"),
        LLMResponse(text="still not json", stop_reason="end_turn"),
    ]


def test_without_live_it_prints_the_estimate_and_calls_nothing(tmp_path, small_cases):
    llm = ScriptedLLMClient([])
    lines: list[str] = []
    code = _run(_args(tmp_path, small_cases), llm=llm, out=lines.append)
    assert code == run_eval.EXIT_REFUSED
    text = "\n".join(lines)
    assert "Cost estimate for 5 cases on claude-sonnet-5-5" in text
    assert "$" in text and "--live" in text
    assert llm.calls == []
    assert not (tmp_path / "out").exists()
    assert not (tmp_path / "scratch").exists()


def test_the_estimate_says_when_a_model_has_no_price():
    cases = load_cases(CASES_FILE)
    est = run_eval.estimate(cases, "deepseek/deepseek-v4.1-flash-1017")
    assert est["priced"] is False and est["expected"]["usd"] is None
    assert "price unknown" in run_eval.format_estimate(est, "openrouter")
    priced = run_eval.estimate(cases, "claude-sonnet-5-5")
    assert priced["expected"]["usd"] > 0
    assert priced["upper"]["usd"] > priced["expected"]["usd"]
    assert priced["expected"]["calls"] == len(cases)


def test_live_run_writes_a_report_scored_with_the_apps_caps(tmp_path, small_cases):
    llm = _BilledClient(_responses())
    lines: list[str] = []
    code = _run(_args(tmp_path, small_cases, "--live"), llm=llm, out=lines.append)
    assert code == run_eval.EXIT_OK, "\n".join(lines)

    (report_path,) = (tmp_path / "out").glob("*-claude-sonnet-5-5.json")
    report = json.loads(report_path.read_text())
    by_id = {c["id"]: c for c in report["cases"]}

    # The app's caps: no mechanism caps 0.9 at 0.5; a named misconception caps at 0.5.
    assert by_id["thin"]["final_score"] == 0.5
    assert by_id["capped"]["final_score"] == 0.5
    assert by_id["hi"]["final_score"] == 0.9
    assert by_id["broken"]["outcome"] == "invalid_output"
    assert by_id["broken"]["error_category"] == "invalid_output"

    m = report["metrics"]
    assert m["false_mastery"]["case_ids"] == ["fluent"]
    assert m["false_cap"]["case_ids"] == ["capped"]
    assert m["false_cap"]["items"] == {"capped": ["always global minimum"]}
    assert m["invalid_output"]["count"] == 1
    assert set(report["baselines"]) == {
        "always_high_no_caps", "always_medium", "always_low", "cap_everything"}

    # Usage went to the scratch database and was priced per case.
    assert by_id["hi"]["calls"] == 1 and by_id["broken"]["calls"] == 2
    assert by_id["hi"]["cost_usd"] == pytest.approx((1000 * 2.0 + 100 * 10.0) / 1e6)
    assert m["cost"]["calls"] == 6
    with sqlite3.connect(tmp_path / "scratch" / "usage.db") as conn:
        rows = conn.execute("SELECT feature FROM llmusage").fetchall()
    assert rows == [("eval_grading",)] * 6

    meta = report["meta"]
    assert meta["model"] == "claude-sonnet-5-5" and meta["prompt_tag"].startswith("assess.grade@")
    assert meta["stopped"] is None
    printed = "\n".join(lines).splitlines()
    assert any(line.startswith("cap_everything") for line in printed)
    assert any(line.startswith("claude-sonnet-5-5") for line in printed)


def test_the_runner_sends_exactly_the_apps_prompt_and_nothing_from_the_truth(tmp_path,
                                                                             small_cases):
    llm = _BilledClient(_responses())
    _run(_args(tmp_path, small_cases, "--live"), llm=llm, out=lambda _: None)
    cases = load_cases(small_cases)
    first = llm.calls[0]
    req = grade_request(cases[0].concept, cases[0].kind, list(cases[0].criteria),
                        cases[0].reference, cases[0].answer,
                        must_include=list(cases[0].required),
                        weak_signs=list(cases[0].misconceptions))
    assert first["system"] == req.system
    assert first["messages"] == [{"role": "user", "content": req.user}]
    assert first["tools"] == []


def test_no_frozen_case_leaks_its_id_truth_or_notes_into_the_prompt():
    for case in load_cases(CASES_FILE):
        req = run_eval.grade_request_for(case)
        prompt = req.system + "\n" + req.user
        assert case.id not in prompt
        assert case.truth.rationale not in prompt
        if case.unsure:
            assert case.unsure not in prompt
        if case.question:
            assert case.question not in prompt  # the app does not send the question either
        # Mangle everything the grader must not see: the prompt is unchanged.
        twin = replace(case, id="zz-other", category="injection", question="?", unsure="?",
                       truth=replace(case.truth, band="low", rationale="leak",
                                     missing_required=case.required))
        twin_req = run_eval.grade_request_for(twin)
        assert (twin_req.system, twin_req.user) == (req.system, req.user)


def test_it_refuses_an_app_database_as_scratch(tmp_path, small_cases):
    db = tmp_path / "app.db"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE assessment (id INTEGER)")
    llm = ScriptedLLMClient([])
    lines: list[str] = []
    args = run_eval.parse_args(["--cases", str(small_cases), "--out-dir",
                                str(tmp_path / "out"), "--scratch-db", str(db), "--live"])
    assert _run(args, llm=llm, out=lines.append) == run_eval.EXIT_REFUSED
    assert "app database" in "\n".join(lines)
    assert llm.calls == []


def test_the_daily_limit_refuses_a_run_it_cannot_afford(tmp_path, small_cases, monkeypatch):
    monkeypatch.setattr(llm_usage.settings, "daily_budget_usd", 0.0001)
    llm = ScriptedLLMClient([])
    lines: list[str] = []
    code = _run(_args(tmp_path, small_cases, "--live"), llm=llm, out=lines.append)
    assert code == run_eval.EXIT_REFUSED
    assert "AA_DAILY_BUDGET_USD" in "\n".join(lines)
    assert llm.calls == []


def test_the_daily_limit_stops_a_run_midway_and_says_so(tmp_path, small_cases, monkeypatch):
    # The limit covers the estimate, but the calls cost more than estimated: the check before
    # each case stops the run once the recorded spend reaches the limit.
    monkeypatch.setattr(run_eval, "EST_OUTPUT_TOKENS", 1)
    monkeypatch.setattr(run_eval, "CHARS_PER_TOKEN", 1e9)

    class _Expensive(ScriptedLLMClient):
        def complete(self, system, messages, tools):
            resp = super().complete(system, messages, tools)
            llm_usage.record_usage(
                backend="anthropic", model="claude-sonnet-5-5", role="reasoning",
                operation="complete", usage=SimpleNamespace(input_tokens=0,
                                                            output_tokens=10_000))
            return resp

    monkeypatch.setattr(llm_usage.settings, "daily_budget_usd", 0.15)
    llm = _Expensive(_responses())
    lines: list[str] = []
    code = _run(_args(tmp_path, small_cases, "--live"), llm=llm, out=lines.append)
    assert code == run_eval.EXIT_STOPPED, "\n".join(lines)
    (report_path,) = (tmp_path / "out").glob("*.json")
    report = json.loads(report_path.read_text())
    outcomes = [c["outcome"] for c in report["cases"]]
    assert outcomes[:2] == ["graded", "graded"] and set(outcomes[2:]) == {"not_run"}
    assert report["meta"]["stopped"].startswith("budget")
    assert report["metrics"]["outcomes"]["not_run"] == 3


def test_live_without_a_key_is_refused_before_any_case(tmp_path, small_cases):
    # No client injected: the runner builds the app's own (api/deps.get_llm), and the
    # conftest has scrubbed every provider key, so it must refuse rather than run.
    lines: list[str] = []
    code = _run(_args(tmp_path, small_cases, "--live"), out=lines.append)
    assert code == run_eval.EXIT_REFUSED
    assert "ANTHROPIC_API_KEY" in "\n".join(lines)
    assert not (tmp_path / "out").exists()


# ── the scratch database persists, so the daily limit is per day ─────────────

def test_the_default_scratch_db_is_a_fixed_gitignored_path_in_results():
    args = run_eval.parse_args([])
    assert args.scratch_db == run_eval.DEFAULT_SCRATCH_DB
    assert run_eval.DEFAULT_SCRATCH_DB == ROOT / "evals" / "grading" / "results" / "usage.db"
    if shutil.which("git") is None:
        pytest.skip("needs git")
    out = subprocess.run(["git", "check-ignore", "-q", str(run_eval.DEFAULT_SCRATCH_DB)],
                         cwd=ROOT, capture_output=True, check=False)
    if out.returncode == 128:
        pytest.skip("not a git checkout")
    assert out.returncode == 0, "evals/grading/results/usage.db must be gitignored"


def test_a_second_run_on_the_same_scratch_db_counts_only_its_own_calls(tmp_path, small_cases):
    for _ in range(2):
        code = _run(_args(tmp_path, small_cases, "--live"), llm=_BilledClient(_responses()),
                    out=lambda _: None)
        assert code == run_eval.EXIT_OK
    reports = sorted((tmp_path / "out").glob("*.json"))
    assert reports  # two runs in the same second share a name; the last one is kept
    report = json.loads(reports[-1].read_text())
    assert report["metrics"]["cost"]["calls"] == 6  # not 12: the first run's rows are old
    with sqlite3.connect(tmp_path / "scratch" / "usage.db") as conn:
        assert conn.execute("SELECT count(*) FROM llmusage").fetchone() == (12,)


def test_the_daily_limit_counts_earlier_runs_on_the_same_day(tmp_path, small_cases,
                                                             monkeypatch):
    monkeypatch.setattr(run_eval, "EST_OUTPUT_TOKENS", 1)
    monkeypatch.setattr(run_eval, "CHARS_PER_TOKEN", 1e9)
    assert _run(_args(tmp_path, small_cases, "--live"), llm=_BilledClient(_responses()),
                out=lambda _: None) == run_eval.EXIT_OK
    spent = 6 * (1000 * 2.0 + 100 * 10.0) / 1e6
    monkeypatch.setattr(llm_usage.settings, "daily_budget_usd", spent)
    lines: list[str] = []
    llm = _BilledClient(_responses())
    assert _run(_args(tmp_path, small_cases, "--live"), llm=llm,
                out=lines.append) == run_eval.EXIT_REFUSED
    assert "refused" in "\n".join(lines) and llm.calls == []
    # A fresh scratch database has no spend today, so the same limit lets the run start.
    fresh = run_eval.parse_args(["--cases", str(small_cases), "--out-dir",
                                 str(tmp_path / "out2"), "--scratch-db",
                                 str(tmp_path / "fresh" / "usage.db"), "--live"])
    assert _run(fresh, llm=_BilledClient(_responses()), out=lambda _: None) in (
        run_eval.EXIT_OK, run_eval.EXIT_STOPPED)


def test_a_budget_stop_inside_a_case_still_counts_that_cases_first_call(tmp_path,
                                                                       small_cases):
    # The real client checks the limit before every call, so the limit can stop a case on
    # its regeneration call, after the first call was billed and recorded.
    class _StopsOnRegeneration(_BilledClient):
        def complete(self, system, messages, tools):
            if len(messages) > 1:  # the GRADE_CORRECTION turn: a regeneration
                raise llm_usage.BudgetExceededError(1.0, 1.0)
            return super().complete(system, messages, tools)

    llm = _StopsOnRegeneration([LLMResponse(text="not json", stop_reason="end_turn")])
    code = _run(_args(tmp_path, small_cases, "--live"), llm=llm, out=lambda _: None)
    assert code == run_eval.EXIT_STOPPED
    (report_path,) = (tmp_path / "out").glob("*.json")
    report = json.loads(report_path.read_text())
    first = report["cases"][0]
    one_call = (1000 * 2.0 + 100 * 10.0) / 1e6
    assert first["outcome"] == "not_run" and first["calls"] == 1
    assert first["cost_usd"] == pytest.approx(one_call)
    assert report["metrics"]["cost"]["total_usd"] == pytest.approx(one_call)
    assert report["metrics"]["cost"]["calls"] == 1
    assert report["meta"]["stopped"].startswith("BudgetExceededError")


# ── the app's database is isolated before the app is imported ────────────────

def test_isolation_raises_once_the_app_is_imported():
    # In this process the app is already imported (tests/conftest.py), so setting
    # AA_DATABASE_URL now could not reach db.engine: it must fail loudly, not do nothing.
    with pytest.raises(RuntimeError, match="already imported"):
        run_eval.isolate_app_database("sqlite://")


def test_main_refuses_when_the_app_was_imported_first(tmp_path, small_cases, capsys):
    code = run_eval.main(["--cases", str(small_cases), "--out-dir", str(tmp_path / "o")])
    assert code == run_eval.EXIT_REFUSED
    assert "already imported" in capsys.readouterr().out


def test_main_in_a_fresh_process_prints_the_estimate_and_refuses_without_live(tmp_path,
                                                                              small_cases):
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(ROOT), str(ROOT / "src")])}
    out = subprocess.run(
        [sys.executable, "-m", "evals.grading.run_eval", "--cases", str(small_cases),
         "--out-dir", str(tmp_path / "o")],
        cwd=tmp_path, env=env, capture_output=True, text=True, check=False, timeout=120)
    assert out.returncode == run_eval.EXIT_REFUSED, out.stderr
    assert "Cost estimate for 5 cases" in out.stdout and "Not run" in out.stdout
    assert not (tmp_path / "o").exists()
