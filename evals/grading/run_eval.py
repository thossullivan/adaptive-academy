"""Run the frozen grading eval against the configured model. Manual and live; never in CI.

    just eval-grading            # prints the cost estimate and stops
    just eval-grading --live     # runs every case against the configured model

Each case goes through the app's own grading path: assess.grade_request builds the prompt
(build_grade_prompt with the rubric items deduplicated as the app does), assess.run_grader
makes the call through the grade gate (output checks, one regeneration, rejection), and
assess.final_score applies the app's caps. The model comes from the app's registry and
client (api/deps.get_llm: AA_LLM_BACKEND, AA_MODEL_REASONING). Nothing here re-implements
any of that.

Usage rows go to a scratch database this script creates (never the app's database), and the
daily limit (AA_DAILY_BUDGET_USD) is checked before the run and before every case against
the spend recorded there. The report is written to results/<timestamp>-<model>.json.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from evals.grading import metrics
from evals.grading.case_file import Case, CaseFileError, load_cases

HERE = Path(__file__).resolve().parent
DEFAULT_CASES = HERE / "cases.jsonl"
DEFAULT_OUT_DIR = HERE / "results"
# The eval's own usage record. A fixed path (not a temp dir per run), so AA_DAILY_BUDGET_USD
# counts every eval run today, as the app's limit does; the results dir is gitignored and is
# not the app's data directory.
DEFAULT_SCRATCH_DB = HERE / "results" / "usage.db"

# The cost estimate is rough on purpose and says so. Input: characters / 3.5 (English with
# formulas tokenises a little denser than the usual 4). Output: thinking plus the JSON grade;
# Sonnet 5.5 thinks adaptively by default, so this is a generous per-call allowance.
CHARS_PER_TOKEN = 3.5
EST_OUTPUT_TOKENS = 1500
EST_CORRECTION_TOKENS = 150  # the GRADE_CORRECTION turn added when a grade is regenerated

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_REFUSED = 2
EXIT_STOPPED = 3

_APP_PREFIX = "adaptive_academy"


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="run_eval", description="Grade the frozen cases with the configured model.")
    p.add_argument("--live", action="store_true",
                   help="actually call the model (without it: print the estimate and stop)")
    p.add_argument("--cases", type=Path, default=DEFAULT_CASES, help="the case file")
    p.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR,
                   help="where the JSON report goes")
    p.add_argument("--scratch-db", type=Path, default=DEFAULT_SCRATCH_DB,
                   help="SQLite file for usage rows; it persists so the daily limit counts "
                        "every run today (default: results/usage.db, gitignored)")
    p.add_argument("--limit", type=int, default=None,
                   help="run only the first N cases (a smoke run)")
    return p.parse_args(argv)


def _app_imported() -> bool:
    return any(m == _APP_PREFIX or m.startswith(_APP_PREFIX + ".") for m in sys.modules)


def isolate_app_database(url: str) -> None:
    """Point the app's database setting at `url` before the app is imported, so nothing it
    builds at import time (db.engine, the default usage bind) names the real database.
    Usage recording is also pointed at the scratch engine explicitly (run()).

    Raises RuntimeError when the app is already imported: settings and db.engine were built
    from whatever AA_DATABASE_URL said then, and setting it now would change nothing."""
    if _app_imported():
        raise RuntimeError(
            "adaptive_academy was already imported before the grading eval could point its "
            "database at the scratch file, so the app's settings (and db.engine) may name "
            "the real database. Run the eval as its own process (`just eval-grading`, or "
            "`python -m evals.grading.run_eval`), not from code that imported the app first.")
    os.environ["AA_DATABASE_URL"] = url


def check_scratch_db(path: Path) -> str | None:
    """Why `path` can't be the scratch database, or None. It must be new, or an earlier
    scratch database (holding only the usage table): an app database is never written."""
    if not path.exists():
        return None
    import sqlite3

    try:
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as conn:
            tables = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
    except sqlite3.DatabaseError:
        return f"{path} exists and is not a SQLite database"
    if tables - {"llmusage"}:
        return (f"{path} holds other tables ({', '.join(sorted(tables)[:3])}...): it looks "
                "like an app database. Pass a new file, or leave --scratch-db out.")
    return None


# ── Prompt and estimate ──────────────────────────────────────────────────────

def grade_request_for(case: Case):
    """The request the app would send for this case (assess.grade_request), built only from
    what the app sends: no id, category, question, truth or note."""
    from adaptive_academy.engine.assess import grade_request

    return grade_request(case.concept, case.kind, list(case.criteria), case.reference,
                         case.answer, must_include=list(case.required),
                         weak_signs=list(case.misconceptions))


def estimate(cases: list[Case], model: str) -> dict[str, Any]:
    """Tokens and dollars for one run, from llm/pricing. `expected`: one call per case;
    `upper`: every case regenerated once (two calls, the second carrying the first answer
    and the correction turn). Prompt caching of the shared system prompt is ignored, so
    real input cost is usually lower."""
    from adaptive_academy.llm.pricing import cost_usd, price_for

    input_tokens = 0
    for case in cases:
        req = grade_request_for(case)
        input_tokens += math.ceil((len(req.system) + len(req.user)) / CHARS_PER_TOKEN)
    n = len(cases)
    expected = {"calls": n, "input_tokens": input_tokens,
                "output_tokens": n * EST_OUTPUT_TOKENS}
    upper = {"calls": 2 * n,
             "input_tokens": 2 * input_tokens + n * (EST_OUTPUT_TOKENS + EST_CORRECTION_TOKENS),
             "output_tokens": 2 * n * EST_OUTPUT_TOKENS}
    priced = price_for(model) is not None
    for row in (expected, upper):
        row["usd"] = (cost_usd(model, input_tokens=row["input_tokens"],
                               output_tokens=row["output_tokens"]) if priced else None)
    return {"model": model, "priced": priced, "cases": n, "expected": expected,
            "upper": upper,
            "assumptions": f"input = characters / {CHARS_PER_TOKEN}; output = "
                           f"{EST_OUTPUT_TOKENS} tokens per call (thinking + JSON); "
                           "prompt caching ignored"}


def format_estimate(est: dict[str, Any], backend: str) -> str:
    e, u = est["expected"], est["upper"]
    lines = [f"Cost estimate for {est['cases']} cases on {est['model']} ({backend}):",
             f"  expected: {e['calls']} calls, ~{e['input_tokens']:,} input + "
             f"~{e['output_tokens']:,} output tokens",
             f"  upper:    {u['calls']} calls (every grade regenerated once), "
             f"~{u['input_tokens']:,} input + ~{u['output_tokens']:,} output tokens"]
    if est["priced"]:
        lines.append(f"  about ${e['usd']:.2f} expected, ${u['usd']:.2f} at most "
                     "(list price, llm/pricing.py)")
    else:
        lines.append("  price unknown: this model is not in llm/pricing.py. On OpenRouter "
                     "each call reports what it cost, and the report adds those up.")
    if backend == "agent_sdk":
        lines.append("  agent_sdk: calls are billed to the Claude subscription, not a key.")
    lines.append(f"  ({est['assumptions']})")
    return "\n".join(lines)


# ── One case ─────────────────────────────────────────────────────────────────

def _usage_since(bind, last_id: int, *,
                 newest_only: bool = False) -> tuple[list[Any], int]:
    """Usage rows recorded after `last_id`, and the new last id. `newest_only`: just the
    newest id (the starting point on a scratch database earlier runs wrote to)."""
    from sqlalchemy import func
    from sqlmodel import Session, select

    from adaptive_academy.engine.trace_writer import TRACE_WRITER
    from adaptive_academy.models import LLMUsage

    TRACE_WRITER.flush()
    if newest_only:
        with Session(bind) as s:
            newest = s.exec(select(func.max(LLMUsage.id))).one()
        return [], int(newest or 0)
    with Session(bind) as s:
        rows = s.exec(select(LLMUsage).where(LLMUsage.id > last_id)
                      .order_by(LLMUsage.id)).all()
        s.expunge_all()
    return rows, (rows[-1].id if rows else last_id)


def run_case(case: Case, llm, session) -> tuple[metrics.Prediction, dict[str, Any]]:
    """Grade one case through the app's path. Returns the prediction and its detail.
    BudgetExceededError and MissingAPIKeyError propagate: they stop the run."""
    from adaptive_academy.engine.assess import final_score, run_grader
    from adaptive_academy.engine.output_checks import match_items
    from adaptive_academy.llm.errors import classify_llm_error
    from adaptive_academy.llm.keys import MissingAPIKeyError
    from adaptive_academy.llm.types import StructuredOutputError
    from adaptive_academy.llm.usage import BudgetExceededError

    events: list[list[str]] = []
    req = grade_request_for(case)
    started = time.monotonic()
    detail: dict[str, Any] = {"id": case.id, "concept": case.concept, "kind": case.kind,
                              "category": case.category}
    try:
        run = run_grader(session, llm, req, emit=lambda k, d="": events.append([k, d]))
    except (BudgetExceededError, MissingAPIKeyError):
        raise
    except StructuredOutputError as exc:  # GradeCheckError, refusal, cut off
        detail.update(outcome="invalid_output", error_category=classify_llm_error(exc),
                      error=str(exc)[:300])
        pred = metrics.Prediction(case.id, "invalid_output")
    except Exception as exc:  # noqa: BLE001 - recorded per case; the run goes on
        detail.update(outcome="error", error_category=classify_llm_error(exc),
                      error=f"{type(exc).__name__}: {str(exc)[:300]}")
        pred = metrics.Prediction(case.id, "error")
    else:
        missing, _ = match_items(run.grade.missing_required, req.required)
        committed, _ = match_items(run.grade.misconceptions_committed, req.misconceptions)
        score = final_score(run.grade, run.rules_gaps)
        pred = metrics.Prediction(case.id, "graded", score, tuple(missing), tuple(committed))
        detail.update(
            outcome="graded", grader_score=run.grade.score,
            mechanism_present=run.grade.mechanism_present, final_score=score,
            band=metrics.band_of(score), verdict=run.grade.verdict, gaps=run.grade.gaps,
            missing_required=list(missing), misconceptions_committed=list(committed),
            attempts=run.answer.attempts, warnings=list(run.answer.report.warned_ids))
    detail["latency_s"] = round(time.monotonic() - started, 3)
    detail["events"] = events
    return pred, detail


def _with_usage(pred: metrics.Prediction, rows: list[Any]) -> metrics.Prediction:
    costs = [r.reported_cost_usd if r.reported_cost_usd is not None else r.cost_usd
             for r in rows]
    known = [c for c in costs if c is not None]
    return metrics.Prediction(
        pred.case_id, pred.outcome, pred.final_score, pred.missing_required,
        pred.misconceptions_committed, cost_usd=sum(known) if known else None,
        latency_s=pred.latency_s, calls=len(rows), unpriced_calls=len(costs) - len(known))


# ── The run ──────────────────────────────────────────────────────────────────

def _slug(model: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", model).strip("-") or "model"


def _truth_dict(case: Case) -> dict[str, Any]:
    t = asdict(case.truth)
    return {k: list(v) if isinstance(v, tuple) else v for k, v in t.items()}


def run(args: argparse.Namespace, *, llm=None, out=print, isolated: bool = False) -> int:
    """`isolated`: the caller already pointed AA_DATABASE_URL away from the real database
    before importing the app (the test suite does, in tests/_isolated_env.py). Otherwise the
    app must not be imported yet, and run() isolates it (isolate_app_database)."""
    try:
        cases = load_cases(args.cases)
    except (OSError, CaseFileError) as exc:
        out(f"refused: {exc}")
        return EXIT_REFUSED
    if args.limit is not None:
        cases = cases[:max(args.limit, 0)]
        if not cases:
            out("refused: --limit leaves no cases")
            return EXIT_REFUSED

    scratch_db: Path | None = None
    if args.live:
        scratch_db = Path(args.scratch_db or DEFAULT_SCRATCH_DB).resolve()
        problem = check_scratch_db(scratch_db)
        if problem:
            out(f"refused: {problem}")
            return EXIT_REFUSED
    if not isolated:
        try:
            # The estimate alone opens no database at all.
            isolate_app_database(f"sqlite:///{scratch_db}" if scratch_db else "sqlite://")
        except RuntimeError as exc:
            out(f"refused: {exc}")
            return EXIT_REFUSED

    from adaptive_academy.llm.backends import (
        KEY_BILLED_BACKENDS,
        api_backend,
        current_backend_name,
    )
    from adaptive_academy.llm.registry import get_model

    backend_name = current_backend_name()
    model = get_model("reasoning")
    est = estimate(cases, model)
    out(format_estimate(est, backend_name))
    if not args.live or scratch_db is None:
        out("\nNot run: add --live to call the model (`just eval-grading --live`).")
        return EXIT_REFUSED

    from sqlmodel import Session, SQLModel, create_engine

    from adaptive_academy.engine.output_checks import GRADE_RUBRIC
    from adaptive_academy.llm import usage
    from adaptive_academy.llm.keys import MissingAPIKeyError
    from adaptive_academy.models import LLMUsage
    from adaptive_academy.prompts import GRADE
    from adaptive_academy.settings import settings

    scratch_db.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{scratch_db}",
                           connect_args={"check_same_thread": False, "timeout": 30})
    SQLModel.metadata.create_all(engine, tables=[LLMUsage.__table__])
    previous_bind = usage.get_usage_bind()
    usage.set_usage_bind(engine)
    key_billed = backend_name in KEY_BILLED_BACKENDS
    reports_cost = api_backend().reports_cost
    limit = settings.daily_budget_usd
    try:
        if limit is not None and key_billed:
            try:
                usage.check_budget(model, reports_cost=reports_cost, backend=backend_name)
            except usage.BudgetExceededError as exc:
                out(f"refused: {exc}")
                return EXIT_REFUSED
            spent = usage.spent_today_usd()
            if est["expected"]["usd"] is not None and spent + est["expected"]["usd"] > limit:
                out(f"refused: the expected cost (${est['expected']['usd']:.2f}) plus today's "
                    f"recorded eval spend (${spent:.2f}) is over AA_DAILY_BUDGET_USD "
                    f"(${limit:.2f}). Raise the limit or use --limit N.")
                return EXIT_REFUSED

        if llm is None:
            from adaptive_academy.api.deps import get_llm
            try:
                llm = get_llm()
            except MissingAPIKeyError as exc:  # no key, or agent_sdk where it can't run
                out(f"refused: {exc}")
                return EXIT_REFUSED

        started_at = datetime.now(timezone.utc)
        preds: list[metrics.Prediction] = []
        details: list[dict[str, Any]] = []
        stopped: str | None = None
        # The scratch database persists across runs: count only this run's rows.
        _, last_id = _usage_since(engine, 0, newest_only=True)
        with Session(engine) as session, usage.feature_context("eval_grading"):
            for i, case in enumerate(cases, start=1):
                if stopped is None and limit is not None and key_billed:
                    try:
                        usage.check_budget(model, reports_cost=reports_cost,
                                           backend=backend_name)
                    except usage.BudgetExceededError as exc:
                        stopped = f"budget: {exc}"
                if stopped is not None:
                    preds.append(metrics.Prediction(case.id, "not_run"))
                    details.append({"id": case.id, "concept": case.concept,
                                    "kind": case.kind, "category": case.category,
                                    "outcome": "not_run"})
                    continue
                try:
                    pred, detail = run_case(case, llm, session)
                except (usage.BudgetExceededError, MissingAPIKeyError) as exc:
                    # Stopped inside the case (e.g. the limit refused its regeneration
                    # call): the calls it already made were billed, so they still count.
                    stopped = f"{type(exc).__name__}: {exc}"
                    rows, last_id = _usage_since(engine, last_id)
                    pred = _with_usage(metrics.Prediction(case.id, "not_run"), rows)
                    preds.append(pred)
                    details.append({"id": case.id, "concept": case.concept,
                                    "kind": case.kind, "category": case.category,
                                    "outcome": "not_run", "stopped_in_case": True,
                                    "calls": pred.calls, "cost_usd": pred.cost_usd,
                                    "unpriced_calls": pred.unpriced_calls})
                    continue
                rows, last_id = _usage_since(engine, last_id)
                pred = _with_usage(metrics.Prediction(
                    pred.case_id, pred.outcome, pred.final_score, pred.missing_required,
                    pred.misconceptions_committed, latency_s=detail["latency_s"]), rows)
                detail.update(calls=pred.calls, cost_usd=pred.cost_usd,
                              unpriced_calls=pred.unpriced_calls)
                detail["truth"] = _truth_dict(case)
                detail["false_mastery"] = metrics.is_false_mastery(case, pred)
                detail["false_cap_items"] = metrics.false_cap_items(case, pred)
                preds.append(pred)
                details.append(detail)
                out(f"[{i}/{len(cases)}] {case.id}: {detail['outcome']}"
                    + (f" {detail['final_score']}" if detail.get("final_score") is not None
                       else ""))
        engine.dispose()
    finally:
        usage.set_usage_bind(previous_bind)

    result = metrics.score(cases, preds)
    baselines = {name: metrics.score(cases, metrics.baseline_predictions(cases, name))
                 for name in metrics.BASELINES}
    for d, case in zip(details, cases):
        d.setdefault("truth", _truth_dict(case))
        if case.unsure:
            d["unsure"] = case.unsure
    report = {
        "meta": {
            "model": model, "backend": backend_name, "prompt_tag": GRADE.tag,
            "rubric": GRADE_RUBRIC.name, "rules": list(GRADE_RUBRIC.ids),
            "cases_file": str(args.cases), "cases_sha256": hashlib.sha256(
                Path(args.cases).read_bytes()).hexdigest(),
            "cases_run": len(cases), "started_at": started_at.isoformat(),
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "stopped": stopped, "scratch_db": str(scratch_db),
            "daily_budget_usd": limit,
            "unsure_case_ids": [c.id for c in cases if c.unsure],
        },
        "estimate": est,
        "metrics": result,
        "baselines": baselines,
        "baseline_notes": metrics.BASELINE_NOTES,
        "cases": details,
    }
    args.out_dir.mkdir(parents=True, exist_ok=True)
    path = args.out_dir / f"{started_at.strftime('%Y%m%dT%H%M%SZ')}-{_slug(model)}.json"
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    out("")
    out(metrics.summary_table(model, result, baselines))
    out("")
    out(f"false mastery: {result['false_mastery']['case_ids'] or 'none'}")
    out(f"false caps:    {result['false_cap']['items'] or 'none'}")
    cost = result["cost"]
    out(f"cost: ${cost['total_usd']:.4f} over {cost['calls']} recorded calls"
        + (f" ({cost['unpriced_calls']} with no known price)" if cost["unpriced_calls"]
           else ""))
    if result["latency"]:
        out(f"latency: mean {result['latency']['mean_s']:.1f}s, "
            f"max {result['latency']['max_s']:.1f}s per case")
    if stopped:
        out(f"stopped early: {stopped}")
    out(f"report: {path}")
    return EXIT_STOPPED if stopped else EXIT_OK


def main(argv: list[str] | None = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
